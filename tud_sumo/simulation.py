import os, sys, io, traci, sumolib, json, csv, math
import traci.constants as tc
import pickle as pkl
from tqdm import tqdm
from copy import copy, deepcopy
from random import choices, choice, random, seed as set_seed
from .events import EventScheduler, Event
from .controllers import VSLController, RGController
from shapely.geometry import LineString, Point
from .utils import *

class Simulation:
    def __init__(self, scenario_name: str|None = None, scenario_desc: str|None = None) -> None:
        """
        :param scenario_name: Scenario label saved to simulation object (defaults to name of '.sumocfg')
        :param scenario_desc: Simulation scenario description, saved along with all files
        """

        path_tools = os.path.join(os.environ.get("SUMO_HOME"), 'tools')

        if path_tools in sys.path: pass
        else: sys.path.append(path_tools)

        self.curr_step = 0
        self.step_length = None
        self.units = Units(1)
        self.scenario_name = scenario_name
        self.scenario_desc = scenario_desc
        self._seed = None
        self._running = False
        self._gui = False

        self._all_data = None

        self.track_juncs = False
        self.tracked_junctions = {}
        self._junc_phases = None
        self._all_juncs = []
        self._all_tls = []

        self._manual_flow = False
        self._demand_sd = 1/3
        self._demand_headers = None
        self._demand_arrs = None
        self._man_flow_id = None

        self.controllers = {}
        self._scheduler = None

        self.tracked_edges = {}
        self.available_detectors = {}

        self._all_edges = None
        self._all_lanes = None
        self._all_routes = None

        self._get_individual_vehicle_data = True
        self._all_curr_vehicle_ids = set([])
        self._all_loaded_vehicle_ids = set([])
        self._all_added_vehicles = set([])
        self._all_removed_vehicles = set([])
        self._all_vehicle_types = set([])
        self._known_vehicles = {}
        self._trips = {"incomplete": {}, "completed": {}}

    def __str__(self):
        if self.scenario_name != None:
            return "<Simulation: '{0}'>".format(self.scenario_name)
        else: return "<Simulation>"

    def __name__(self): return "Simulation"

    def __dict__(self): return {} if self._all_data == None else self._all_data

    def start(self, config_file: str|None = None, net_file: str|None = None, route_file: str|None = None, add_file: str|None = None, cmd_options: list|None = None, units: str|int = 1, get_individual_vehicle_data: bool = True, automatic_subscriptions: bool = True, suppress_warnings: bool = False, ignore_TraCI_err: bool = False, seed: str = "random", gui: bool = False) -> None:
        """
        Intialises SUMO simulation.
        :param config_file: Location of '.sumocfg' file (can be given instead of net_file)
        :param net_file:    Location of '.net.xml' file (can be given instead of config_file)
        :param route_file:  Location of '.rou.xml' route file
        :param add_file:    Location of '.add.xml' additional file
        :param cmd_options: List of any other command line options
        :param units:       Data collection units [1 (metric) | 2 (IMPERIAL) | 3 (UK)] (defaults to 'metric')
        :param get_individual_vehicle_data: Denotes whether to get individual vehicle data (set to False to improve performance)
        :param automatic_subscriptions: Denotes whether to automatically subscribe to commonly used vehicle data (speed and position, defaults to True)
        :param suppress_warnings: Suppress simulation warnings
        :param ignore_TraCI_err: If true and a fatal traCI error occurs, the simulation ends but the program continues to run
        :param seed:        Either int to be used as seed, or random.random()/random.randint(), where a random seed is used
        :param gui:         Bool denoting whether to run GUI
        """

        self._gui = gui
        sumoCMD = ["sumo-gui"] if self._gui else ["sumo"]

        if config_file == net_file == None:
            desc = "Either config or network file required."
            raise_error(ValueError, desc, self.curr_step)
        
        if config_file != None:
            if config_file.endswith(".sumocfg"):
                sumoCMD += ["-c", config_file]
                if self.scenario_name == None: self.scenario_name = get_scenario_name(config_file)
            else:
                desc = "Invalid config file extension."
                raise_error(ValueError, desc, self.curr_step)
        else:
            sumoCMD += ["-n", net_file]
            if self.scenario_name == None: self.scenario_name = get_scenario_name(net_file)
            if route_file != None: sumoCMD += ["-r", route_file]
            if add_file != None: sumoCMD += ["-a", add_file]
        
        if cmd_options != None: sumoCMD += cmd_options

        if seed != None:
            if isinstance(seed, str):
                if seed.upper() != "RANDOM" and not seed.isdigit():
                    desc = "Invalid seed '{0}' (must be valid 'int' or str 'random').",format(seed)
                    raise_error(ValueError, desc)
                elif seed.upper() == "RANDOM":
                    sumoCMD.append("--random")
                else:
                    sumoCMD += ["--seed", seed]
                    set_seed(int(seed))
                    np.random.seed(int(seed))
            elif isinstance(seed, int):
                sumoCMD += ["--seed", str(seed)]
                set_seed(seed)
                np.random.seed(seed)
            else:
                desc = "Invalid seed '{0}' type (must be 'str', not '{1}').".format(seed, type(seed).__name__)
                raise_error(TypeError, desc, self.curr_step)
        
        self._seed = int(seed) if seed.upper() != "RANDOM" else seed
 
        if isinstance(units, str):
            if units.upper() in ["METRIC", "IMPERIAL", "UK"]:
                self.units = Units(["METRIC", "IMPERIAL", "UK"].index(units.upper())+1)
            else:
                desc = "Invalid simulation units '{0}' (must be ['METRIC'|'IMPERIAL'|'UK']).".format(units)
                raise_error(ValueError, desc, self.curr_step)

        elif units in [1, 2, 3]: self.units = Units(units)
        else:
            desc = "Invalid simulation units '{0}' (must be ['METRIC'|'IMPERIAL'|'UK']).".format(units)
            raise_error(ValueError, desc, self.curr_step)

        traci.start(sumoCMD)
        self._running = True

        self.step_length = float(traci.simulation.getOption("step-length"))

        if self._junc_phases != None: self._update_lights()
        self._time_val = traci.simulation.getTime()

        for detector_id in list(traci.multientryexit.getIDList()):
            self.available_detectors[detector_id] = {'type': 'multientryexit', 'position': {'entry_lanes': traci.multientryexit.getEntryLanes(detector_id),
                                                                                            'exit_lanes': traci.multientryexit.getExitLanes(detector_id),
                                                                                            'entry_positions': traci.multientryexit.getEntryPositions(detector_id),
                                                                                            'exit_positions': traci.multientryexit.getExitPositions(detector_id)}}
            self.add_detector_subscriptions(detector_id, ["vehicle_ids", "lsm_speed"])
            
        for detector_id in list(traci.inductionloop.getIDList()):
            self.available_detectors[detector_id] = {'type': 'inductionloop', 'position': {'lane_id': traci.inductionloop.getLaneID(detector_id), 'position': traci.inductionloop.getPosition(detector_id)}}
            self.add_detector_subscriptions(detector_id, ["vehicle_ids", "lsm_speed", "lsm_occupancy"])

        self._all_juncs = list(traci.junction.getIDList())
        self._all_tls = list(traci.trafficlight.getIDList())
        self._all_edges = list(traci.edge.getIDList())
        self._all_lanes = list(traci.lane.getIDList())
        self._all_vehicle_types = set(traci.vehicletype.getIDList())

        self.network_file = traci.simulation.getOption("net-file")
        self.network = sumolib.net.readNet(self.network_file)

        all_route_ids, self._all_routes = list(traci.route.getIDList()), {}
        for route_id in all_route_ids:
            self._all_routes[route_id] = traci.route.getEdges(route_id)

        self._get_individual_vehicle_data = get_individual_vehicle_data
        self._automatic_subscriptions = automatic_subscriptions

        self._ignore_TraCI_err = ignore_TraCI_err
        self._suppress_warnings = suppress_warnings

        self._sim_start_time = get_time_str()

    def load_objects(self, object_parameters: dict|str) -> None:
        """
        Load all parameters for TUD SUMO objects: tracked edges/junctions, signal
        phases, controllers and events.
        :param object_parameters: Either dict containing object parameters or '.json|.pkl' filepath
        """
        
        if isinstance(object_parameters, str):

            if object_parameters.endswith(".json"): r_class, r_mode = json, "r"
            elif object_parameters.endswith(".pkl"): r_class, r_mode = pkl, "rb"
            else:
                desc = "Invalid object parameter file '{0}' (must be '.json' or '.pkl).".format(object_parameters)
                raise_error(ValueError, desc, self.curr_step)

            if os.path.exists(object_parameters):
                with open(object_parameters, r_mode) as fp:
                    object_parameters = r_class.load(fp)
            else:
                desc = "Object parameter file '{0}' not found.".format(object_parameters)
                raise_error(FileNotFoundError, desc, self.curr_step)

        elif not isinstance(object_parameters, dict):
            desc = "Invalid object_parameters type given '{0}' (must be [dict|str], not '{1}').".format(object_parameters, type(object_parameters).__name__)
            raise_error(TypeError, desc, self.curr_step)

        valid_params = {"edges": list, "junctions": dict, "phases": dict, "controllers": dict, "events": dict, "demand": str}
        error, desc = test_input_dict(object_parameters, valid_params, "'object parameters")
        if error != None: raise_error(error, desc, self.sim.curr_step)
        
        if "edges" in object_parameters:
            self.add_tracked_edges(object_parameters["edges"])

        if "junctions" in object_parameters:
            self.add_tracked_junctions(object_parameters["junctions"])

        if "phases" in object_parameters:
            self.set_phases(object_parameters["phases"], overwrite=True)
        
        if "controllers" in object_parameters:
            self.add_controllers(object_parameters["controllers"])

        if "events" in object_parameters:
            self.add_events(object_parameters["events"])

        if "demand" in object_parameters:
            self.load_demand(object_parameters["demand"])
    
    def load_demand(self, csv_file: str) -> None:
        """
        Loads OD demand from a '.csv' file. The file must contain an 'origin/destination' or 'route_id'
        column(s), 'start_time/end_time' or 'start_step/end_step' columns(s) and a 'demand/number' column.
        :param csv_file: Demand file location.
        """

        if isinstance(csv_file, str):
            if csv_file.endswith(".csv"):
                if os.path.exists(csv_file):
                    with open(csv_file, "r") as fp:
                        valid_cols = ["origin", "destination", "route_id", "start_time", "end_time", "start_step", "end_step",
                                  "demand", "number", "vehicle_types", "vehicle_type_dists", "initial_speed", "origin_lane"]
                        demand_idxs = {}
                        reader = csv.reader(fp)
                        for idx, row in enumerate(reader):
                            if idx == 0:

                                if len(set(row) - set(valid_cols)) != 0:
                                    desc = "Invalid demand file (unknown columns '{0}').".format("', '".join(list(set(row) - set(valid_cols))))
                                    raise_error(KeyError, desc, self.curr_step)

                                if "route_id" in row: demand_idxs["route_id"] = row.index("route_id")
                                elif "origin" in row and "destination" in row:
                                    demand_idxs["origin"] = row.index("origin")
                                    demand_idxs["destination"] = row.index("destination")
                                else:
                                    desc = "Invalid demand file (no routing values, must contain 'route_id' or 'origin/destination')."
                                    raise_error(KeyError, desc, self.curr_step)
                                
                                if "start_time" in row and "end_time" in row:
                                    demand_idxs["start_time"] = row.index("start_time")
                                    demand_idxs["end_time"] = row.index("end_time")
                                elif "start_step" in row and "end_step" in row:
                                    demand_idxs["start_step"] = row.index("start_step")
                                    demand_idxs["end_step"] = row.index("end_step")
                                else:
                                    desc = "Invalid demand file (no time values, must contain 'start_time/end_time' or 'start_step/end_step')."
                                    raise_error(KeyError, desc, self.curr_step)

                                if "demand" in row: demand_idxs["demand"] = row.index("demand")
                                elif "number" in row: demand_idxs["number"] = row.index("number")
                                else:
                                    desc = "Invalid demand file (no demand values, must contain 'demand/number')."
                                    raise_error(KeyError, desc, self.curr_step)

                                if "vehicle_types" in row:
                                    demand_idxs["vehicle_types"] = row.index("vehicle_types")
                                
                                if "vehicle_type_dists" in row and "vehicle_types" in row:
                                    demand_idxs["vehicle_type_dists"] = row.index("vehicle_type_dists")

                                if "initial_speed" in row:
                                    demand_idxs["initial_speed"] = row.index("initial_speed")

                                if "origin_lane" in row:
                                    demand_idxs["origin_lane"] = row.index("vehiorigin_lanecle_types")

                            else:
                                
                                if "route_id" in demand_idxs: routing = row[demand_idxs["route_id"]]
                                else: routing = (row[demand_idxs["origin"]], row[demand_idxs["destination"]])

                                if "start_time" in demand_idxs: 
                                    step_range = (int(row[demand_idxs["start_time"]]) / self.step_length, int(row[demand_idxs["end_time"]]) / self.step_length)
                                else: step_range = (int(row[demand_idxs["start_step"]]), int(row[demand_idxs["end_step"]]))

                                if "number" in demand_idxs: demand = int(row[demand_idxs["number"]]) / convert_units(step_range[1] - step_range[0], "steps", "hours", self.step_length)
                                else: demand = float(row[demand_idxs["demand"]])

                                if "vehicle_types" in demand_idxs:
                                    vehicle_types = row[demand_idxs["vehicle_types"]].split(",")
                                    if len(vehicle_types) == 1: vehicle_types = vehicle_types[0]
                                else: vehicle_types = "default"

                                if "vehicle_type_dists" in demand_idxs:
                                    vehicle_type_dists = row[demand_idxs["vehicle_type_dists"]].split(",")
                                    if len(vehicle_type_dists) != len(vehicle_types):
                                        desc = "Invalid vehicle_type_dists '[{0}]' (must be same length as vehicle_types '{1}').".format(", ".join(vehicle_type_dists), len(vehicle_types))
                                        raise_error(ValueError, desc, self.curr_step)
                                    else: vehicle_type_dists = [float(val) for val in vehicle_type_dists]
                                else: vehicle_type_dists = 1 if isinstance(vehicle_types, str) else [1]*len(vehicle_types)

                                if "initial_speed" in demand_idxs:
                                    initial_speed = row[demand_idxs["initial_speed"]]
                                    if initial_speed.isdigit(): initial_speed = float(initial_speed)
                                else: initial_speed = "max"

                                if "origin_lane" in demand_idxs:
                                    origin_lane = row[demand_idxs["origin_lane"]]
                                    if origin_lane.isdigit(): origin_lane = int(origin_lane)
                                else: origin_lane = "best"

                                self.add_demand(routing, step_range, demand, vehicle_types, vehicle_type_dists, initial_speed, origin_lane)
                                
                else:
                    desc = "Demand file '{0}' not found.".format(csv_file)
                    raise_error(FileNotFoundError, desc, self.curr_step)
            else:
                desc = "Invalid demand file '{0}' format (must be '.csv').".format(csv_file)
                raise_error(ValueError, desc, self.curr_step)
        else:
            desc = "Invalid demand file '{0}' (must be 'str' filepath, not '{1}').",format(csv_file, type(csv_file).__name__)
            raise_error(TypeError, desc, self.curr_step)

        self._manual_flow = True

    def add_demand(self, routing: str|list|tuple, step_range: list|tuple, demand: int|float, vehicle_types: str|list|tuple|None=None, vehicle_type_dists: list|tuple|None=None, initial_speed: str|int|float="max", origin_lane: str|int|float="best"):
        """
        Adds traffic flow demand for a specific route and time.
        :param routing: Either a route ID or OD pair of edge IDs
        :param step_range: (2x1) list or tuple denoting the start and end steps of the demand
        :param demand: Generated flow in vehicles/hour
        :param vehicle_types: List of vehicle type IDs
        :param vehicle_type_dists: Vehicle type distributions used when generating flow
        :param initial_speed: Initial speed at insertion, either ['max'|'random'] or number > 0
        :param origin_lane:   Lane for insertion at origin, either ['random'|'free'|'allowed'|'best'|'first'] or lane index
        """

        if isinstance(routing, str) and not self.route_exists(routing):
            desc = "Unknown route ID '{0}'.".format(routing)
            raise_error(KeyError, desc, self.curr_step)
        elif isinstance(routing, (list, tuple)):
            if len(routing) == 2:
                if self.geometry_exists(routing[0]) != "edge":
                    desc = "Unknown origin edge ID '{0}'.".format(routing[0])
                    raise_error(KeyError, desc, self.curr_step)
                elif self.geometry_exists(routing[1]) != "edge":
                    desc = "Unknown destination edge ID '{0}'.".format(routing[1])
                    raise_error(KeyError, desc, self.curr_step)
            else:
                desc = "Invalid routing '{0}' (OD-pairs must be (2x1) [list|tuple]).".format(routing)
                raise_error(KeyError, desc, self.curr_step)
        else:
            desc = "Invalid routing '{0}' type (must be (2x1) [list|tuple] or route ID, not '{1}').".format(routing, type(routing).__name__)
            raise_error(TypeError, desc, self.curr_step)

        if not isinstance(step_range, (list, tuple)):
            desc = "Invalid step_range '{0}' type (must be (2x1) [list|tuple], not '{1}').".format(step_range, type(step_range).__name__)
            raise_error(TypeError, desc, self.curr_step)
        elif False in [isinstance(val, (int, float)) for val in step_range]:
            desc = "Invalid step_range '{0}' type (must only contain values of type [int|float]).".format(step_range)
            raise_error(TypeError, desc, self.curr_step)
        elif step_range[1] < step_range[0] or step_range[1] < self.curr_step:
            desc = "Invalid step_range '{0}' (must be valid range and end > current step)."
            raise_error(ValueError, desc, self.curr_step)

        if vehicle_types != None:
            if not isinstance(vehicle_types, (str, list, tuple)):
                desc = "Invalid vehicle_types '{0}' type (must be [str|list|tuple], not '{1}').".format(vehicle_types, type(vehicle_types).__name__)
                raise_error(TypeError, desc, self.curr_step)
            if isinstance(vehicle_types, (list, tuple)):
                for type_id in vehicle_types:
                    if not self.vehicle_type_exists(type_id):
                        desc = "Unknown vehicle type ID '{0}' in vehicle_types.".format(type_id)
                        raise_error(KeyError, desc, self.curr_step)
            elif isinstance(vehicle_types, str) and not self.vehicle_type_exists(type_id):
                desc = "Unknown vehicle type ID '{0}' in vehicle_types.".format(type_id)
                raise_error(KeyError, desc, self.curr_step)
        
        if vehicle_type_dists != None and vehicle_types == None:
            desc = "vehicle_type_dists given, but no vehicle types."
            raise_error(ValueError, desc, self.curr_step)
        elif vehicle_type_dists != None and isinstance(vehicle_types, str):
            desc = "Invalid vehicle_type_dists (vehicle_types is a single type ID, so no distribution)."
            raise_error(ValueError, desc, self.curr_step)
        elif vehicle_type_dists != None:
            if not isinstance(vehicle_type_dists, (list, tuple)):
                desc = "Invalid vehicle_type_dists '{0}' type (must be [list|tuple], not '{1}').".format(vehicle_type_dists, type(vehicle_type_dists).__name__)
                raise_error(TypeError, desc, self.curr_step)
            elif len(vehicle_type_dists) != len(vehicle_types):
                desc = "Invalid vehicle_type_dists (must be same length as vehicle_types, {0} != {1}).".format(len(vehicle_type_dists), len(vehicle_types))
                raise_warning(ValueError, desc, self.curr_step)
            elif False in [isinstance(val, (float)) for val in vehicle_type_dists]:
                desc = "Invalid vehicle_type_dists '{0}' type (must only contain values of type 'float').".format(vehicle_type_dists)
                raise_error(TypeError, desc, self.curr_step)

        if not self._manual_flow:
            self._manual_flow = True
            self._demand_headers = ["routing", "step_range", "veh/step", "vehicle_types", "vehicle_type_dists", "init_speed", "origin_lane"]
            self._demand_arrs, self._man_flow_id = [], 0

        self._demand_arrs.append([routing, step_range, demand, vehicle_types, vehicle_type_dists, initial_speed, origin_lane])

    def _add_demand_vehicles(self) -> None:
        """
        Implements demand in the demand table.
        """

        if self._manual_flow:
            
            for demand_arr in self._demand_arrs:
                step_range = demand_arr[1]
                if self.curr_step < step_range[0]: continue
                elif self.curr_step > step_range[1]: continue

                routing = demand_arr[0]
                veh_per_step = (demand_arr[2] / 3600) * self.step_length
                vehicle_types = demand_arr[3]
                vehicle_type_dists = demand_arr[4]
                initial_speed = demand_arr[5]
                origin_lane = demand_arr[6]
                
                added = 0
                if veh_per_step < 1: n_vehicles = 1 if random() < veh_per_step else 0
                else: n_vehicles = round(np.random.normal(veh_per_step, veh_per_step * self._demand_sd, 1)[0])

                while added < n_vehicles:
                    if isinstance(vehicle_types, list):
                        vehicle_type = choices(vehicle_types, vehicle_type_dists, k=1)[0]
                    else: vehicle_type = vehicle_types

                    vehicle_id = "{0}_md_{1}".format(vehicle_type, self._man_flow_id)
                    
                    self.add_vehicle(vehicle_id, vehicle_type, routing, initial_speed, origin_lane)

                    added += 1
                    self._man_flow_id += 1

        else:
            if not self._suppress_warnings:
                desc = "Cannot add flow manually as no demand given."
                raise_warning(desc, self.curr_step)

    def add_tracked_junctions(self, juncs: str|list|dict|None = None) -> None:
        """
        Initalise junctions and start tracking states and flows.
        :param juncs: Either junc_id|list of junc_ids, or dict containing juncs parameters. Defaults to all junctions with traffic lights.
        """

        self.track_juncs = True

        if juncs == None: # If none given, track all junctions with traffic lights
            track_list, junc_params = self._all_tls, None
        else:
            
            if isinstance(juncs, dict):
                junc_ids, junc_params = list(juncs.keys()), juncs
            elif isinstance(juncs, (list, tuple)):
                junc_ids, junc_params = juncs, None
            elif isinstance(juncs, str):
                junc_ids, junc_params = [juncs], None
            else:
                desc = "Invalid junc_params (must be [str|list|dict], not '{0}').".format(type(juncs).__name__)
                raise_error(TypeError, desc, self.curr_step)

            if len(set(self._all_juncs).intersection(set(junc_ids))) != len(junc_ids):
                desc = "Junction ID(s) not found ('{0}').".format("', '".join(set(junc_ids) - set(self._all_juncs)))
                raise_error(KeyError, desc, self.curr_step)
            else: track_list = junc_ids

        for junc_id in track_list:
            if junc_id not in self.tracked_junctions:
                junc_param = junc_params[junc_id] if junc_params != None else None
                self.tracked_junctions[junc_id] = TrackedJunction(junc_id, self, junc_param)
                self.tracked_junctions[junc_id].update_vals = True
            else:
                desc = "Junction with ID '{0}' already exists.".format(junc_id)
                raise_error(ValueError, desc, self.curr_step)

    def reset_data(self) -> None:
        """
        Resets data collection.
        """

        for junction in self.tracked_junctions.values():
            junction.reset()

        for edge in self.tracked_edges.values():
            edge.reset()

        for controller in self.controllers.values():
            controller.reset()

        self._trips = {"incomplete": {}, "completed": {}}

        self._sim_start_time = get_time_str()
        self._all_data = None

    def is_running(self, close: bool=True) -> bool:
        """
        Returns whether the simulation is running.
        :param close: If True, end Simulation
        :return bool: Denotes if the simulation is running
        """
        if not self._running: return self._running

        if traci.simulation.getMinExpectedNumber() == 0:
            if self._demand_arrs != None:
                if len(self._demand_arrs) > 0:
                    for arr in self._demand_arrs:
                        if arr[1][1] > self.curr_step: return True
            if close: self.end()
            print('Ended simulation: no vehicles remaining.')
            return False
        
        return True

    def end(self) -> None:
        """
        Ends the simulation.
        """

        try:
            traci.close()
        except traci.exceptions.FatalTraCIError:
            raise_warning("TraCI is not connected.", self.curr_step)
        self._running = False

    def save_data(self, filename: str|None = None, overwrite: bool = True, json_indent: int|None = 4) -> None:
        """
        Save all vehicle, detector and junction data in a JSON or pickle file.
        :param filename:  Output filepath (defaults to ./'scenario_name'.json)
        :param overwrite: Prevent previous outputs being overwritten
        """

        if filename == None: filename = self.scenario_name

        if filename.endswith(".json"):
            w_class, w_mode = json, "w"
        elif filename.endswith(".pkl"):
            w_class, w_mode = pkl, "wb"
        else:
            filename += ".json"
            w_class, w_mode = json, "w"

        if os.path.exists(filename) and overwrite:
            if not self._suppress_warnings: raise_warning("File '{0}' already exists and will be overwritten.".format(filename), self.curr_step)
        elif os.path.exists(filename) and not overwrite:
            desc = "File '{0}' already exists and cannot be overwritten.".format(filename)
            raise_error(FileExistsError, desc, self.curr_step)

        if self._all_data != None:
            if self._scheduler != None: self._all_data["data"]["events"] = self._scheduler.__dict__()
            with open(filename, w_mode) as fp:
                if w_mode == "wb": w_class.dump(self._all_data, fp)
                else: w_class.dump(self._all_data, fp, indent=json_indent)
        else:
            desc = "No data to save as a simulation has not been run."
            raise_error(IndexError, desc, self.curr_step)

    def add_tracked_edges(self, edge_ids=None):
        """
        Initalise edges and start collecting data.
        :param edge_ids: List of edge IDs or single ID, defaults to all
        """
        if edge_ids == None: edge_ids = self._all_edges
        if isinstance(edge_ids, str): edge_ids = [edge_ids]
        elif not isinstance(edge_ids, (list, tuple)):
            desc = "Invalid edge_ids '{0}' type (must be [str|list|tuple], not '{1}').".format(edge_ids, type(edge_ids).__name__)
            raise_error(TypeError, desc, self.curr_step)

        for edge_id in edge_ids:
            if self.geometry_exists(edge_id) == None:
                desc = "Geometry ID '{0}' not found.".format(edge_id)
                raise_error(KeyError, desc, self.curr_step)
            elif edge_id in self.tracked_edges:
                desc = "Tracked geometry with ID '{0}' already exists.".format(edge_id)
                raise_error(ValueError, desc, self.curr_step)
            self.tracked_edges[edge_id] = TrackedEdge(edge_id, self)

    def add_events(self, event_params: Event|list|dict|str) -> None:
        """
        Add events and event scheduler.
        :param event_parms: Event parameters [Event|[Event]|dict|filepath]
        """
        if self._scheduler == None:
            self._scheduler = EventScheduler(self)
        self._scheduler.add_events(event_params)

    def add_controllers(self, controller_params: str|dict) -> dict:
        """
        Add controllers from parameters in a dictionary/JSON file.
        :param controller_params: Controller parameters dictionary or filepath
        """

        controller_params = load_params(controller_params, "controller_params", self.curr_step)

        for c_id, c_params  in controller_params.items():
            if c_id in self.controllers:
                desc = "Controller with ID '{0}' already exists.".format(c_id)
                raise_error(ValueError, desc, self.curr_step)
            if isinstance(c_params, (RGController, VSLController)):
                self.controllers[c_id] = c_params
            elif isinstance(c_params, dict):
                if 'type' not in c_params.keys():
                    desc = "No type given (must be [1 (RG)|2 (VSL)])."
                    raise_error(KeyError, desc, self.curr_step)
                if c_params['type'] in [1, 2, "VSL", "RG"]:
                    
                    if c_params['type'] in [1, "VSL"]: controller = VSLController(c_id, c_params, self)
                    elif c_params['type'] in [2, "RG"]: controller = RGController(c_id, c_params, self)
                    
                    self.controllers[c_id] = controller

                else:
                    desc = "Invalid controller type (must be [1 (RG)|2 (VSL)])."
                    raise_error(ValueError, desc, self.curr_step)
            else:
                desc = "Invalid parameters type in dictionary (must be [dict|RGController|VSLController], not '{0}').".format(type(c_params).__name__)
                raise_error(TypeError, desc, self.curr_step)

        return self.controllers

    def step_through(self, n_steps: int = 1, end_step: int|None = None, sim_dur: int|None = None, vehicle_types: list|None = None, keep_data: bool = True, append_data: bool = True, pbar: tqdm|None = None) -> dict:
        """
        Step through simulation from the current time until end_step, aggregating data during this period.
        :param n_steps:         Perform n steps of the simulation (defaults to 1)
        :param end_step:        End point for stepping through simulation (given instead of end_step)
        :param sim_dur:         Simulation duration
        :param vehicle_types:   Vehicle type(s) to collect data of (list of types or string, defaults to all)
        :param keep_data:       Denotes whether to store data collected during this run (defaults to True)
        :param append_data:     Denotes whether to append simulation data to that of previous runs (defaults to True)
        :param pbar:            tqdm progress bar updated by 1 with each step, used to 
        :return dict:           All data collected through the time period, separated by detector
        """

        if not self.is_running(): return

        if append_data == True: prev_data = self._all_data
        else: prev_data = None

        detector_list = list(self.available_detectors.keys())
        start_time = self.curr_step

        if end_step == None and n_steps != None: end_step = self.curr_step + n_steps
        elif end_step == None and sim_dur != None: end_step = self.curr_step + (sim_dur / self.step_length)
        elif end_step == None: 
            desc = "No time value given."
            raise_error(ValueError, desc, self.curr_step)

        if prev_data == None:
            prev_steps, all_data = 0, {"scenario_name": self.scenario_name, "scenario_desc": "", "data": {}, "start": start_time, "end": self.curr_step, "step_len": self.step_length, "units": self.units.name, "seed": self._seed, "sim_start": self._sim_start_time, "sim_end": get_time_str()}
            
            if self.scenario_desc == None: del all_data["scenario_desc"]
            else: all_data["scenario_desc"] = self.scenario_desc

            if len(self.available_detectors) > 0: all_data["data"]["detectors"] = {}
            if self.track_juncs: all_data["data"]["junctions"] = {}
            if len(self.tracked_edges) > 0: all_data["data"]["edges"] = {}
            if len(self.controllers) > 0: all_data["data"]["controllers"] = {}
            all_data["data"]["vehicles"] = {}
            if self._manual_flow and self._demand_arrs != None:
                all_data["data"]["demand"] = {"headers": self._demand_headers, "table": self._demand_arrs}
            all_data["data"]["trips"] = {"incomplete": {}, "completed": {}}
            if self._get_individual_vehicle_data: all_data["data"]["all_vehicles"] = []
            if self._scheduler != None: all_data["data"]["events"] = {}
        else: 
            prev_steps = set([len(data_arr) for data_arr in prev_data["data"]["vehicles"].values()] +
                            [len(detector_data["speeds"]) for detector_data in prev_data["data"]["detectors"].values()] +
                            [len(detector_data["vehicle_counts"]) for detector_data in prev_data["data"]["detectors"].values()])
            
            if len(prev_steps) != 1:
                desc = "Invalid prev_data (different length arrays)."
                raise_error(ValueError, desc, self.curr_step)
            else:
                prev_steps = prev_steps.pop()
                all_data = prev_data

        if not isinstance(pbar, tqdm):
            if not self._gui and n_steps > 1: pbar = tqdm(desc="Running sim (step {0}, {1} vehs)".format(self.curr_step, len(self._all_curr_vehicle_ids)), total=end_step - self.curr_step)

        while self.curr_step < end_step:

            try: last_step_data, all_v_data = self._step(vehicle_types)
            except traci.exceptions.FatalTraCIError:
                self._running = False
                if self._ignore_TraCI_err:
                    if not self._suppress_warnings: raise_warning("Fatal TraCI connection error occured.", self.curr_step)
                    break
                else:
                    desc = "Fatal TraCI connection error occured."
                    raise_error(traci.exceptions.FatalTraCIError, desc, self.curr_step)

            if self._get_individual_vehicle_data: all_data["data"]["all_vehicles"].append(all_v_data)
            for controller in self.controllers.values(): controller.update()
            for edge in self.tracked_edges.values(): edge.update()

            if len(all_data["data"]["detectors"]) == 0:
                for detector_id in detector_list:
                    all_data["data"]["detectors"][detector_id] = self.available_detectors[detector_id]
                    all_data["data"]["detectors"][detector_id].update({"speeds": [], "vehicle_counts": [], "vehicle_ids": [], "occupancies": []})
                all_data["data"]["vehicles"] = {"no_vehicles": [], "no_waiting": [], "tts": [], "delay": []}

            for detector_id in last_step_data["detectors"].keys():
                if detector_id not in all_data["data"]["detectors"].keys():
                    desc = "Unrecognised detector ID found ('{0}').".format(detector_id)
                    raise_error(KeyError, desc, self.curr_step)
                for data_key, data_val in last_step_data["detectors"][detector_id].items():
                    all_data["data"]["detectors"][detector_id][data_key].append(data_val)

            for data_key, data_val in last_step_data["vehicles"].items():
                all_data["data"]["vehicles"][data_key].append(data_val)

            all_data["data"]["trips"] = self._trips

            if isinstance(pbar, tqdm):
                pbar.update(1)
                pbar.set_description("Running sim (step {0}, {1} vehs)".format(self.curr_step, len(self._all_curr_vehicle_ids)))

        all_data["end"] = self.curr_step
        all_data["sim_end"] = get_time_str()
        if self.track_juncs: all_data["data"]["junctions"] = last_step_data["junctions"]
        if self._scheduler != None: all_data["data"]["events"] = self._scheduler.__dict__()
        for e_id, edge in self.tracked_edges.items(): all_data["data"]["edges"][e_id] = edge.__dict__()
        for c_id, controller in self.controllers.items(): all_data["data"]["controllers"][c_id] = controller.__dict__()

        if keep_data:
            self._all_data = all_data
            return all_data
        else:
            self.reset_data()
            return None

    def _step(self, vehicle_types: list|None = None) -> dict:
        """
        Increment simulation by one time step, updating light state. step_through is recommended to run the simulation.
        :param vehicle_types: Vehicle type(s) to collect data of (list of types or string, defaults to all)
        :return dict:         Simulation data
        """

        self.curr_step += 1

        data = {"detectors": {}, "vehicles": {}}
        if self.track_juncs: data["junctions"] = {}

        if self._manual_flow:
            self._add_demand_vehicles()
        
        traci.simulationStep()
        time_diff = traci.simulation.getTime() - self._time_val
        self._time_val = traci.simulation.getTime()

        all_prev_vehicle_ids = self._all_curr_vehicle_ids
        self._all_curr_vehicle_ids = set(traci.vehicle.getIDList())
        self._all_loaded_vehicle_ids = set(traci.vehicle.getLoadedIDList())
        self._all_to_depart_vehicle_ids = self._all_loaded_vehicle_ids - self._all_curr_vehicle_ids

        all_vehicles_in = self._all_curr_vehicle_ids - all_prev_vehicle_ids
        all_vehicles_out = all_prev_vehicle_ids - self._all_curr_vehicle_ids

        if self._automatic_subscriptions:
            subscriptions = ["speed", "lane_idx"]
            if self._get_individual_vehicle_data: subscriptions += ["acceleration", "heading", "altitude"]
            else: subscriptions.append("position")

            self.add_vehicle_subscriptions(list(all_vehicles_in), subscriptions)

        self._vehicles_in(all_vehicles_in)
        self._vehicles_out(all_vehicles_out)

        if self._junc_phases != None:
            update_junc_lights = []
            for junction_id, phases in self._junc_phases.items():
                phases["curr_time"] += time_diff
                if phases["curr_time"] >= phases["cycle_len"]:
                    phases["curr_time"] = 0
                    phases["curr_phase"] = 0
                    update_junc_lights.append(junction_id)

                # Change to a while loop, updating phase until correct is found? Would then allow for phases with dur less than the step len
                elif phases["curr_time"] >= sum(phases["times"][:phases["curr_phase"] + 1]):
                    phases["curr_phase"] += 1
                    update_junc_lights.append(junction_id)

            self._update_lights(update_junc_lights)

        if self._scheduler != None: self._scheduler.update_events()

        detector_list = list(self.available_detectors.keys())
        for detector_id in detector_list:
            data["detectors"][detector_id] = {}
            if detector_id not in self.available_detectors.keys():
                desc = "Unrecognised detector ID found ('{0}').".format(detector_id)
                raise_error(KeyError, desc, self.curr_step)
            if self.available_detectors[detector_id]["type"] == "multientryexit":

                detector_data = self.get_detector_vals(detector_id, ["lsm_speed", "vehicle_count"])
                data["detectors"][detector_id]["speeds"] = detector_data["lsm_speed"]
                data["detectors"][detector_id]["vehicle_counts"] = detector_data["vehicle_count"]
                
            elif self.available_detectors[detector_id]["type"] == "inductionloop":

                detector_data = self.get_detector_vals(detector_id, ["lsm_speed", "vehicle_count", "lsm_occupancy"])
                data["detectors"][detector_id]["speeds"] = detector_data["lsm_speed"]
                data["detectors"][detector_id]["vehicle_counts"] = detector_data["vehicle_count"]
                data["detectors"][detector_id]["occupancies"] = detector_data["lsm_occupancy"]

            else:
                if not self._suppress_warnings: raise_warning("Unknown detector type '{0}'.".format(self.available_detectors[detector_id]["type"]), self.curr_step)

            data["detectors"][detector_id]["vehicle_ids"] = self.get_last_step_detector_vehicles(detector_id)

        no_vehicles, no_waiting, all_v_data = self.get_all_vehicle_data(vehicle_types=vehicle_types, all_dynamic_data=False)
        data["vehicles"]["no_vehicles"] = no_vehicles
        data["vehicles"]["no_waiting"] = no_waiting
        data["vehicles"]["tts"] = no_vehicles * self.step_length
        data["vehicles"]["delay"] = no_waiting * self.step_length

        if self.track_juncs:
            for junc_id, junc in self.tracked_junctions.items():
                junc.update()
                data["junctions"][junc_id] = junc.__dict__()

        return data, all_v_data
    
    def get_no_vehicles(self) -> int:
        """
        Returns the number of vehicles in the simulation during the last simulation step.
        :return int: No. of vehicles
        """
        
        if self._all_data == None:
            desc = "No data to return (simulation likely has not been run, or data has been reset)."
            raise_error(KeyError, desc, self.curr_step)
        return self._all_data["data"]["vehicles"]["no_vehicles"][-1]
    
    def get_no_waiting(self) -> float:
        """
        Returns the number of waiting vehicles in the simulation during the last simulation step.
        :return float: No. of waiting vehicles
        """
        
        if self._all_data == None:
            desc = "No data to return (simulation likely has not been run, or data has been reset)."
            raise_error(KeyError, desc, self.curr_step)
        return self._all_data["data"]["vehicles"]["no_waiting"][-1]
    
    def get_tts(self) -> int:
        """
        Returns the total time spent by vehicles in the simulation during the last simulation step.
        :return float: TTS
        """
        
        if self._all_data == None:
            desc = "No data to return (simulation likely has not been run, or data has been reset)."
            raise_error(KeyError, desc, self.curr_step)
        return self._all_data["data"]["vehicles"]["tts"][-1]
    
    def get_delay(self) -> int:
        """
        Returns the total delay of vehicles during the last simulation step.
        :return float: Total delay
        """
        
        if self._all_data == None:
            desc = "No data to return (simulation likely has not been run, or data has been reset)."
            raise_error(KeyError, desc, self.curr_step)
        return self._all_data["data"]["vehicles"]["delay"][-1]

    def _vehicles_in(self, vehicle_ids: str|list|tuple, is_added: bool=False) -> None:

        if isinstance(vehicle_ids, str): vehicle_ids = [vehicle_ids]
        elif isinstance(vehicle_ids, set): vehicle_ids = list(vehicle_ids)
        elif not isinstance(vehicle_ids, (list, tuple)):
            desc = "Invalid vehicle_ids given '{0}' (must be [str|(str)], not '{1}').".format(vehicle_ids, type(vehicle_ids).__name__)
            raise_error(TypeError, desc, self.curr_step)

        for vehicle_id in vehicle_ids:

            if vehicle_id not in self._all_curr_vehicle_ids: self._all_curr_vehicle_ids.add(vehicle_id)
            if vehicle_id not in self._all_loaded_vehicle_ids: self._all_loaded_vehicle_ids.add(vehicle_id)
            if vehicle_id not in self._all_added_vehicles and is_added: self._all_added_vehicles.add(vehicle_id)

            veh_data = self.get_vehicle_vals(vehicle_id, ("type", "route_id", "route_edges"))
            veh_type, route_id, origin, destination = veh_data["type"], veh_data["route_id"], veh_data["route_edges"][0], veh_data["route_edges"][-1]
            self._trips["incomplete"][vehicle_id] = {"route_id": route_id,
                                                     "vehicle_type": veh_type,
                                                     "departure": self.curr_step,
                                                     "origin": origin,
                                                     "destination": destination}
            
    def _vehicles_out(self, vehicle_ids: str|list|tuple, is_removed: bool=False) -> None:

        if isinstance(vehicle_ids, str): vehicle_ids = [vehicle_ids]
        elif isinstance(vehicle_ids, set): vehicle_ids = list(vehicle_ids)
        elif not isinstance(vehicle_ids, (list, tuple)):
            desc = "Invalid vehicle_ids given '{0}' (must be [str|(str)], not '{1}').".format(vehicle_ids, type(vehicle_ids).__name__)
            raise_error(TypeError, desc, self.curr_step)

        for vehicle_id in vehicle_ids:

            if self.vehicle_loaded(vehicle_id) and self.vehicle_to_depart(vehicle_id): continue
            
            if is_removed or vehicle_id in self._all_removed_vehicles:
                if vehicle_id in self._trips["incomplete"].keys():
                    self._trips["incomplete"][vehicle_id]["removal"] = self.curr_step
                if vehicle_id not in self._all_removed_vehicles:
                    self._all_removed_vehicles.add(vehicle_id)
                if vehicle_id in self._all_curr_vehicle_ids:
                    self._all_curr_vehicle_ids.remove(vehicle_id)
                if vehicle_id in self._all_loaded_vehicle_ids:
                    self._all_loaded_vehicle_ids.remove(vehicle_id)
                continue

            if vehicle_id in self._trips["incomplete"].keys():
                trip_data = self._trips["incomplete"][vehicle_id]
                veh_type, route_id, departure, origin, destination = trip_data["vehicle_type"], trip_data["route_id"], trip_data["departure"], trip_data["origin"], trip_data["destination"]
                del self._trips["incomplete"][vehicle_id]
                self._trips["completed"][vehicle_id] = {"route_id": route_id, "vehicle_type": veh_type, "departure": departure, "arrival": self.curr_step, "origin": origin, "destination": destination}
            
            else:
                if vehicle_id in self._known_vehicles.keys():
                    trip_data = {}
                    if "departure" in self._known_vehicles[vehicle_id].keys():
                        trip_data["departure"] = self._known_vehicles[vehicle_id]["departure"]
                    if "arrival" in self._known_vehicles[vehicle_id].keys():
                        trip_data["arrival"] = self._known_vehicles[vehicle_id]["arrival"]
                    if "origin" in self._known_vehicles[vehicle_id].keys():
                        trip_data["origin"] = self._known_vehicles[vehicle_id]["origin"]
                    if "destination" in self._known_vehicles[vehicle_id].keys():
                        trip_data["destination"] = self._known_vehicles[vehicle_id]["destination"]    
                else: 
                    desc = "Unrecognised vehicle ID '{0}' in completed trips.".format(vehicle_id)
                    raise_error(KeyError, desc, self.curr_step)
                    
    def get_last_step_detector_vehicles(self, detector_ids: str|list|tuple, vehicle_types: list|None = None, flatten: bool = False) -> dict|list:
        """
        Get the IDs of vehicles that passed over the specified detectors.
        :param detector_ids:  Detector ID or list of IDs (defaults to all)
        :param vehicle_types: Included vehicle types
        :param flatten:       If true, all IDs are returned in a 1D array, else a dict with vehicles for each detector
        :return dict|list:    Dict or list containing all vehicle IDs
        """

        detector_ids = [detector_ids] if not isinstance(detector_ids, (list, tuple)) else detector_ids
        if len(detector_ids) == 1: flatten = True
        vehicle_types = [vehicle_types] if vehicle_types != None and not isinstance(vehicle_types, (list, tuple)) else vehicle_types

        vehicle_ids = [] if flatten else {}
        for detector_id in detector_ids:
            
            if detector_id not in self.available_detectors.keys():
                desc = "Detector ID '{0}' not found.".format(detector_id)
                raise_error(KeyError, desc, self.curr_step)
            
            detected_vehicles = self.get_detector_vals(detector_id, "vehicle_ids")
            
            if vehicle_types != None:
                detected_vehicles = [vehicle_id for vehicle_id in detected_vehicles if self.get_vehicle_vals(vehicle_id, "type") in vehicle_types]

            if flatten: vehicle_ids += detected_vehicles
            else: vehicle_ids[detector_id] = detected_vehicles

        if flatten: vehicle_ids = list(set(vehicle_ids))

        return vehicle_ids
    
    def get_detector_vals(self, detector_ids: list|tuple|str, data_keys: str|list) -> int|float|dict:
        """
        Get data values from a specific detector using a list of data keys.
        :param detector_ids: Detector ID or list of IDs
        :param data_keys:    List of keys from [type|position|vehicle_count|vehicle_ids|lsm_speed|halting_no (MEE only)|lsm_occupancy (IL only)|last_detection (IL only)], or single key
        :return dict:        Values by data_key (or single value)
        """

        all_data_vals = {}
        if isinstance(detector_ids, str): detector_ids = [detector_ids]
        elif not isinstance(detector_ids, (list, tuple)):
            desc = "Invalid detector_ids given '{0}' (must be [str|(str)], not '{1}').".format(detector_ids, type(detector_ids).__name__)
            raise_error(TypeError, desc, self.curr_step)

        for detector_id in detector_ids:
            if detector_id not in self.available_detectors.keys():
                desc = "Detector with ID '{0}' not found.".format(detector_id)
                raise_error(KeyError, desc, self.curr_step)
            else:
                detector_type = self.available_detectors[detector_id]["type"]

                match detector_type:
                    case "multientryexit": d_class = traci.multientryexit
                    case "inductionloop": d_class = traci.inductionloop
                    case "_":
                        desc = "Only 'multientryexit' and 'inductionloop' detectors are currently supported (not '{0}').".format(detector_type)
                        raise_error(ValueError, desc, self.curr_step)

            detector_data, subscribed_data = {}, d_class.getSubscriptionResults(detector_id)
            if not isinstance(data_keys, (list, tuple)): data_keys = [data_keys]
            for data_key in data_keys:

                match data_key:
                    case "type":
                        detector_data[data_key] = detector_type

                    case "position":
                        detector_data[data_key] = self.available_detectors[detector_id][data_key]

                    case "vehicle_count":
                        if tc.LAST_STEP_VEHICLE_ID_LIST in subscribed_data: vehicle_count = len(list(subscribed_data[tc.LAST_STEP_VEHICLE_ID_LIST]))
                        elif tc.LAST_STEP_VEHICLE_NUMBER in subscribed_data: vehicle_count = subscribed_data[tc.LAST_STEP_VEHICLE_NUMBER]
                        else: vehicle_count = d_class.getLastStepVehicleNumber(detector_id)
                        detector_data[data_key] = vehicle_count

                    case "vehicle_ids":
                        if tc.LAST_STEP_VEHICLE_ID_LIST in subscribed_data: vehicle_ids = subscribed_data[tc.LAST_STEP_VEHICLE_ID_LIST]
                        else: vehicle_ids = d_class.getLastStepVehicleIDs(detector_id)
                        detector_data[data_key] = list(vehicle_ids)

                    case "lsm_speed":
                        if self.get_detector_vals(detector_id, "vehicle_count") > 0:
                            if tc.LAST_STEP_MEAN_SPEED in subscribed_data: speed = subscribed_data[tc.LAST_STEP_MEAN_SPEED]
                            else: speed = d_class.getLastStepMeanSpeed(detector_id)
                            
                            if speed > 0:
                                units = "kmph" if self.units.name == "METRIC" else "mph"
                                speed = convert_units(speed, "m/s", units)
                            detector_data[data_key] = speed
                        else: detector_data[data_key] = -1

                    case _:
                        valid_keys = {"multientryexit": ["halting_no"], "inductionloop": ["last_detection", "lsm_occupancy"]}
                        
                        if data_key not in [item for row in list(valid_keys.values()) for item in row]:
                            desc = "Unrecognised data key ('{0}').".format(data_key)
                            raise_error(KeyError, desc, self.curr_step)
                        else:
                            if data_key not in valid_keys[detector_type]:
                                desc = "Invalid data key '{0}' for detector type '{1}'.".format(data_key, detector_type)
                                raise_error(KeyError, desc, self.curr_step)

                        match detector_type:
                            case "multientryexit":
                                if tc.LAST_STEP_VEHICLE_HALTING_NUMBER in subscribed_data: halting_no = subscribed_data[tc.LAST_STEP_VEHICLE_HALTING_NUMBER]
                                else: halting_no = d_class.getLastStepHaltingNumber(detector_id)
                                detector_data[data_key] = halting_no
                                
                            case "inductionloop":
                                if data_key == "lsm_occupancy":
                                    if tc.LAST_STEP_OCCUPANCY in subscribed_data: occupancy = subscribed_data[tc.LAST_STEP_OCCUPANCY]
                                    else: occupancy = d_class.getLastStepOccupancy(detector_id)
                                    detector_data[data_key] = occupancy
                                elif data_key == "last_detection":
                                    if tc.LAST_STEP_TIME_SINCE_DETECTION in subscribed_data: last_detection = subscribed_data[tc.LAST_STEP_TIME_SINCE_DETECTION]
                                    else: last_detection = d_class.getTimeSinceDetection(detector_id)
                                    detector_data[data_key] = last_detection
            
            if len(detector_ids) == 1:
                if len(data_keys) == 1: return detector_data[data_keys[0]]
                else: return detector_data
            else:
                if len(data_keys) == 1: all_data_vals[detector_id] = detector_data[data_keys[0]]
                else: all_data_vals[detector_id] = detector_data
        
        return all_data_vals

    def get_interval_detector_data(self, detector_id: int|str, n_steps: int, data_keys: str|list, avg_vals: bool = False) -> float|dict:
        """
        Get data previously collected by a detector over range (curr step - n_step -> curr_step).
        :param detector_id: Detector ID
        :param n_steps:     Interval length in steps (max at number of steps the simulation has run)
        :param data_keys:   List of keys from [vehicle_counts|speeds|occupancy (induction loop only)], or single key
        :param avg_bool:    Bool denoting whether to average values
        :return float|dict: Either single value or dict containing values by data_key
        """

        if self._all_data == None:
            desc = "No detector data as the simulation has not been run or data has been reset."
            raise_error(IndexError, desc, self.curr_step)
        elif detector_id not in self.available_detectors.keys() or detector_id not in self._all_data["data"]["detectors"].keys():
            desc = "Detector with ID '{0}' not found.".format(detector_id)
            raise_error(KeyError, desc, self.curr_step)

        detector_data = {}
        if not isinstance(data_keys, (list, tuple)): data_keys = [data_keys]
        for data_key in data_keys:
            if data_key in ["vehicle_counts", "speeds", "occupancies"]:
                if data_key in self._all_data["data"]["detectors"][detector_id].keys():
                    data_arr = self._all_data["data"]["detectors"][detector_id][data_key][-n_steps:]
                    if avg_vals: data_arr = sum(data_arr) / len(data_arr)
                else:
                    desc = "Detector '{0}' of type '{1}' does not collect '{2}' data.".format(detector_id, self._all_data["data"]["detectors"][detector_id]["type"], data_key)
                    raise_error(KeyError, desc, self.curr_step)
            else:
                desc = "Unrecognised data key ('{0}').".format(data_key)
                raise_error(KeyError, desc, self.curr_step)
            detector_data[data_key] = data_arr

        if len(data_keys) == 1: return detector_data[data_keys[0]]
        else: return detector_data

    def set_phases(self, new_junc_phases: dict, start_phase: int = 0, overwrite: bool = True) -> None:
        """
        Sets the phases for the simulation, starting at the next simulation step.
        :param new_junc_phases: Junction phases and times dictionary
        :param start_phase:     Phase number to start at, defaults to 0
        :param overwrite:       If true, the junc_phases dict is overwitten with new_junc_phases. If false, only specific junctions are overwritten.
        """

        # junc_phases = {junction_0: {phases: [phase_0, phase_1], times: [time_0, time_1]}, ...}
        # where phases are light strings and times are phase length

        if overwrite or self._junc_phases == None:
            self._junc_phases = new_junc_phases
        else:
            for junc_id, new_phases in new_junc_phases.items():
                self._junc_phases[junc_id] = deepcopy(new_phases)

        for junc_id in new_junc_phases.keys():

            if junc_id not in list(traci.trafficlight.getIDList()):
                desc = "Junction with ID '{0}' does not exist, or it does not have a traffic light.".format(junc_id)
                raise_error(KeyError, desc, self.curr_step)

            junc_phase = self._junc_phases[junc_id]

            valid_params = {"times": list, "phases": list}
            error, desc = test_input_dict(junc_phase, valid_params, "'{0}' flow".format(junc_id), required=True)
            if error != None: raise_error(error, desc, self.sim.curr_step)

            for t in junc_phase["times"]:
                if t < self.step_length:
                    desc = "Invalid phase duration (phase_dur ({0}) < resolution ({1}))\n.  - {2}".format(t, self.step_length, junc_phase)
                    raise_error(ValueError, desc, self.curr_step)

            if "curr_phase" not in junc_phase.keys(): junc_phase["curr_phase"] = start_phase
            if junc_phase["curr_phase"] > len(junc_phase["phases"]): junc_phase["curr_phase"] -= len(junc_phase["phases"])

            junc_phase["curr_time"] = sum(junc_phase["times"][:junc_phase["curr_phase"]])
            junc_phase["cycle_len"] = sum(junc_phase["times"])

        self._update_lights(new_junc_phases.keys())

    def set_tl_colour(self, junction_id: str|int, colour_str: str) -> None:
        """
        Sets a junction to a set colour/phase string for an indefinite amount of time. Can be used when tracking phases separately.
        :param junction_id: Junction ID
        :param colour_str:  Colour character ([r|y|g|-]) or phase string ([r|y|g|-]+)
        """
        
        if junction_id not in list(traci.trafficlight.getIDList()):
            desc = "Junction with ID '{0}' does not exist, or it does not have a traffic light.".format(junction_id)
            raise_error(KeyError, desc, self.curr_step)
        else:
            if junction_id in self.tracked_junctions.keys():
                m_len = self.tracked_junctions[junction_id].m_len
            else:
                state_str = traci.trafficlight.getRedYellowGreenState(junction_id)
                m_len = len(state_str)

        if not isinstance(colour_str, str):
            desc = "Invalid colour_str (must be 'str', not '{0}').".format(type(colour_str).__name__)
            raise_error(TypeError, desc, self.curr_step)
        
        if len(colour_str) == 1:
            junc_phases = {junction_id: {"phases": [colour_str*m_len], "times": [math.inf]}}
        elif len(colour_str) == m_len:
            junc_phases = {junction_id: {"phases": [colour_str], "times": [math.inf]}}
        else:
            desc = "Invalid colour_str (must be char or len(str) == junction movements length)."
            raise_error(ValueError, desc, self.curr_step)
        
        self.set_phases(junc_phases, overwrite=False)

    def set_tl_metering_rate(self, rm_id: str|int, metering_rate: int|float, g_time: int|float = 1, y_time: int|float = 1, min_red: int|float = 1, control_interval: int = 60) -> dict:
        """
        Set ramp metering rate of a meter at a junction. Uses a one-car-per-green policy with a default
        1s green and yellow time, with red phase duration changed to set flow. All phase durations must
        be larger than the simulation step length.
        :param rm_id:            Ramp meter (junction) ID
        :param metering_rate:    On-ramp inflow in veh/hr (from all lanes)
        :param g_time:           Green phase duration (s), defaults to 1
        :param y_time:           Yellow phase duration (s), defaults to 1
        :param min_red:          Minimum red phase duration (s), defaults to 1
        :param control_interval: Ramp meter control interval (s) (control interval % cycle length = 0)
        :return dict:            Resulting phase dictionary
        """
        
        if min([g_time, y_time, min_red]) <= self.step_length:
            desc = "Green ({0}), yellow ({1}) and minimum red ({2}) times must all be greater than sim step length ({3}).".format(g_time, y_time, min_red, self.step_length)

        if rm_id not in list(traci.trafficlight.getIDList()):
            desc = "Junction with ID '{0}' does not exist, or it does not have a traffic light.".format(rm_id)
            raise_error(KeyError, desc, self.curr_step)
        else:
            if rm_id in self.tracked_junctions.keys():
                m_len = self.tracked_junctions[rm_id].m_len
            else:
                state_str = traci.trafficlight.getRedYellowGreenState(rm_id)
                m_len = len(state_str)

        if self.track_juncs and rm_id in self.tracked_junctions.keys():
            self.tracked_junctions[rm_id].metering_rates.append(metering_rate)
            self.tracked_junctions[rm_id].rate_times.append(self.curr_step)

        max_flow = (3600 / (g_time + y_time + min_red)) * m_len
        
        # With one lane and a g_time, y_time and min_red of 1s, the meter cannot physically release
        # more than 1200 veh/hr without reducing minimum red. So, to stop the meter continually
        # flipping from g-y-r, the meter is set to green for the whole control interval.

        # This maximum flow is increased with 2 (or more) lanes as, even with 1s green time, this essentially
        # becomes a two-car-per-green policy, and so the maximum flow is doubled.
        if metering_rate > max_flow:
            phases_dict = {"phases": ["G"*m_len], "times": [control_interval/self.step_length]}
        elif metering_rate == 0:
            phases_dict = {"phases": ["r"*m_len], "times": [control_interval/self.step_length]}
        elif metering_rate < 0:
            desc = "Metering rate must be greater than 0 (set to '{0}').".format(metering_rate)
            raise_error(ValueError, desc, self.curr_step)
        else:

            # vehs_per_ci = vehicles released/control interval/lane
            vehs_per_ci = ((metering_rate * control_interval) / 3600) / m_len
            
            # red time calculated with the number of cycles per control interval, minus g + y time
            cycle_length = control_interval / vehs_per_ci
            red_time = cycle_length - g_time - y_time

            # Control interval should be divisible by resulting cycle length as below!
            # sum(phase["times"])/self.step_length * vehs_per_ci == control_interval / self.step_length
            phases_dict = {"phases": ["G"*m_len, "y"*m_len, "r"*m_len],
                        "times":  [g_time / self.step_length, y_time / self.step_length, red_time / self.step_length]}
            
        self.set_phases({rm_id: phases_dict}, overwrite=False)
        return phases_dict

    def change_phase(self, junction_id: str|int, phase_no: int) -> None:
        """
        Change to a different phase at the specified junction_id.
        :param junction_id: Junction ID
        :param phase_no:    Phase number
        """
        
        if 0 < phase_no < len(self._junc_phases[junction_id]["phases"]):
            self._junc_phases[junction_id]["curr_phase"] = phase_no
            self._junc_phases[junction_id]["curr_time"] = sum(self.junc_phase["times"][:phase_no])

            self._update_lights(junction_id)

        else:
            desc = "Invalid phase number '{0}' (must be [0-{1}]).".format(phase_no, len(self._junc_phases[junction_id]["phases"]))
            raise_error(ValueError, desc, self.curr_step)

    def _update_lights(self, junction_ids: list|str = None) -> None:
        """
        Update light settings for given junctions.
        :param junction_ids: Junction ID, or list of IDs (defaults to all)
        """

        if junction_ids is None: junction_ids = self._junc_phases.keys()
        elif isinstance(junction_ids, str): junction_ids = [junction_ids]

        for junction_id in junction_ids:
            curr_setting = traci.trafficlight.getRedYellowGreenState(junction_id)
            new_phase = self._junc_phases[junction_id]["phases"][self._junc_phases[junction_id]["curr_phase"]]
            if '-' in new_phase:
                new_phase = new_phase.split()
                new_phase = "".join([new_phase[i] if new_phase[i] != '-' else curr_setting[i] for i in range(len(new_phase))])
            traci.trafficlight.setRedYellowGreenState(junction_id, new_phase)

    def add_vehicle(self, vehicle_id: str, vehicle_type: str, routing: str|list|tuple, initial_speed: str|float="max", origin_lane: str|int="best") -> None:
        """
        Add a new vehicle into the simulation.
        :param vehicle_id:    ID for new vehicle, must be unique
        :param vehicle_type:  Vehicle type ID for new vehicle
        :param routing:       Either route ID or (2x1) list of edge IDs for origin-destination pair
        :param initial_speed: Initial speed at insertion, either ['max'|'random'] or number > 0
        :param origin_lane:   Lane for insertion at origin, either ['random'|'free'|'allowed'|'best'|'first'] or lane index
        """

        if self.vehicle_exists(vehicle_id):
            desc = "Invalid vehicle_id given '{0}' (must be unique).".format(vehicle_id)
            raise_error(ValueError, desc, self.curr_step)
        
        if not isinstance(initial_speed, (str, int, float)):
            desc = "Invalid initial_speed given '{0}' (must be [str|float], not '{1}').".format(initial_speed, type(initial_speed).__name__)
            raise_error(TypeError, desc, self.curr_step)
        elif isinstance(initial_speed, str) and initial_speed not in ["max", "random"]:
            desc = "Invalid initial_speed string given '{0}' (must be ['max'|'random']).".format(initial_speed, type(initial_speed).__name__)
            raise_error(TypeError, desc, self.curr_step)
        elif isinstance(initial_speed, (int, float)) and initial_speed < 0:
            desc = "Invalid initial_speed value given '{0}' (must be > 0).".format(initial_speed, type(initial_speed).__name__)
            raise_error(TypeError, desc, self.curr_step)

        if not self.vehicle_type_exists(vehicle_type) and vehicle_type != "default":
            desc = "Vehicle type ID '{0}' not found.".format(vehicle_type)
            raise_error(TypeError, desc, self.curr_step)

        if not isinstance(origin_lane, (str, int)):
            desc = "Invalid origin_lane given '{0}' (must be [random|free|allowed|best|first] or lane index).".format(origin_lane)
            raise_error(type, desc, self.curr_step)

        if isinstance(initial_speed, (int, float)):
            units = "kmph" if self.units.name == "METRIC" else "mph"
            initial_speed = convert_units(initial_speed, units, "m/s")

        if isinstance(routing, str):
            route_id = routing
            routing = self.route_exists(route_id)
            if routing != None:
                if vehicle_type != "default": traci.vehicle.add(vehicle_id, route_id, vehicle_type, departLane=origin_lane, departSpeed=initial_speed)
                else: traci.vehicle.add(vehicle_id, route_id, departLane=origin_lane, departSpeed=initial_speed)
            else:
                desc = "Route ID '{0}' not found.".format(route_id)
                raise_error(KeyError, desc, self.curr_step)

        elif isinstance(routing, (list, tuple)):
            if len(routing) == 2:
                for geometry_id in routing:
                    g_class = self.geometry_exists(geometry_id)
                    if g_class == "lane":
                        desc = "Invalid geometry type (Edge ID required, '{0}' is a lane).".format(geometry_id)
                        raise_error(TypeError, desc, self.curr_step)
                    
                    if g_class not in ["edge", "lane"]:
                        desc = "Edge ID '{0}' not found.".format(geometry_id)
                        raise_error(KeyError, desc, self.curr_step)

                    if isinstance(origin_lane, int):
                        n_lanes = self.get_geometry_vals(geometry_id, "n_lanes")
                        if origin_lane >= n_lanes or origin_lane < 0:
                            desc = "Invalid origin lane index '{0}' (must be (0 <= origin_lane < n_lanes '{1}'))".format(origin_lane, n_lanes)
                            raise_error(ValueError, desc, self.curr_step)

                route_id = "_".join(routing)

                if self.route_exists(route_id) == None:
                    traci.route.add(route_id, routing)
                    self._all_routes[route_id] = tuple(routing)

                if vehicle_type != "default": traci.vehicle.add(vehicle_id, route_id, vehicle_type, departLane=origin_lane, departSpeed=initial_speed)
                else: traci.vehicle.add(vehicle_id, route_id, departLane=origin_lane, departSpeed=initial_speed)
                self._vehicles_in(vehicle_id)

            else:
                desc = "Invalid routing given '[{0}]' (must have shape (2x1)).".format(",".join(routing))
                raise_error(TypeError, desc, self.curr_step)
        else:
            desc = "Invalid routing given '{0}' (must be [str|(str)], not '{1}').".format(routing, type(routing).__name__)
            raise_error(TypeError, desc, self.curr_step)
    
    def remove_vehicles(self, vehicle_ids: str|list|tuple) -> None:
        """
        Remove a vehicle or list of vehicles from the simulation.
        :param vehicle_ids: List of vehicle IDs or single ID
        """
        
        if isinstance(vehicle_ids, str): vehicle_ids = [vehicle_ids]
        elif not isinstance(vehicle_ids, (list, tuple)):
            desc = "Invalid vehicle_ids given '{0}' (must be [str|(str)], not '{1}').".format(vehicle_ids, type(vehicle_ids).__name__)
            raise_error(TypeError, desc, self.curr_step)

        for vehicle_id in vehicle_ids:
            if self.vehicle_exists(vehicle_id):
                traci.vehicle.remove(vehicle_id, reason=tc.REMOVE_VAPORIZED)
                self._vehicles_out(vehicle_id, is_removed=True)
            else:
                desc = "Unrecognised vehicle ID given ('{0}').".format(vehicle_id)
                raise_error(KeyError, desc, self.curr_step)

    def cause_incident(self, duration: int, vehicle_ids: str|list|tuple=None, geometry_ids: str|list|tuple=None, n_vehicles: int=1, vehicle_separation=0, assert_n_vehicles: bool=False, edge_speed: int|float|None=-1, highlight_vehicles: bool=True, incident_id: str=None) -> bool:
        """
        Simulates an incident by stopping vehicles on the road for
        a period of time, before removing them from the simulation.
        Vehicles are either chosen randomly, randomly but constrained
        to set edges, or by passing a list of vehicle IDs.
        :param duration: Duration of incident (in simulation steps)
        :param vehicle_ids: List of IDs for vehicles to include in the incident (overrides geometry_ids)
        :param geometry_ids: List of edge IDs to randomly select vehicles from
        :param n_vehicles: Number of vehicles in the incident, if randomly chosen
        :param vehicle_separation: Factor denoting how separated randomly chosen vehicles are (0.1-1)
        :param assert_n_vehicles: Denotes whether to throw an error if the correct number of vehicles cannot be found
        :param edge_speed: New max speed for edges where incident vehicles are located (defaults to 15km/h or 10mph)
        :param highlight_vehicles: Denotes whether to highlight vehicles in the SUMO GUI
        :param incident_id: Incident event ID used in the simulation data file
        """
        
        if incident_id == None:
            id_idx = 1
            while self._scheduler.get_event_status("incident_{0}".format(id_idx)) != None: id_idx += 1
            incident_id = "incident_{0}".format(id_idx)

        event_dict = {"start_time": (self.curr_step + 1) * self.step_length, "end_time": (self.curr_step + duration) * self.step_length,
                      "vehicles": {"actions": {"speed": 0}, "effect_duration": duration, "remove_affected_vehicles": True,
                                   "speed_safety_checks": False, "lc_safety_checks": False}}
        
        check_n_vehicles = vehicle_ids == None
        if geometry_ids == None and vehicle_ids == None:
            if n_vehicles < len(self._all_curr_vehicle_ids) and n_vehicles > 0:
                all_geometry_ids, geometry_ids, vehicle_ids, found_central = list(self._all_edges), [], [], False
                while not found_central:
                    central_id = choice(all_geometry_ids)
                    found_central = self.get_geometry_vals(central_id, "vehicle_count") > 0

                vehicle_separation = min(0.9, max(0, vehicle_separation))
                searched, to_search, prob = [], [central_id], 1 - vehicle_separation
                while len(vehicle_ids) < n_vehicles and len(to_search) > 0:
                    curr_geometry_id = choice(to_search)

                    all_geometry_vehicles = self.get_geometry_vals(curr_geometry_id, "vehicle_ids")
                    
                    for g_veh_id in all_geometry_vehicles:
                        if random() < prob:
                            vehicle_ids.append(g_veh_id)
                            geometry_ids.append(curr_geometry_id)
                            if len(vehicle_ids) >= n_vehicles:
                                break

                    if len(vehicle_ids) < n_vehicles:
                        to_search.remove(curr_geometry_id)
                        searched.append(curr_geometry_id)
                        
                        connected_edges = self.get_geometry_vals(curr_geometry_id, "connected_edges")
                        to_search += connected_edges['incoming']
                        to_search += connected_edges['outgoing']

                        to_search = [g_id for g_id in to_search if g_id not in searched]

                geometry_ids = list(set(geometry_ids))

            else:
                desc = "Invalid n_vehicles '{0}' (must be 0 < '{0}' < no. vehicles in the simulation '{1}').".format(n_vehicles, len(self._all_curr_vehicle_ids))
                raise_error(ValueError, desc, self.curr_step)

        elif geometry_ids != None:
            if isinstance(geometry_ids, str): geometry_ids = [geometry_ids]
            elif not isinstance(geometry_ids, (list, tuple)):
                desc = "Invalid geometry_ids given '{0}' (must be [str|(str)], not '{1}').".format(geometry_ids, type(geometry_ids).__name__)
                raise_error(TypeError, desc, self.curr_step)

            all_geometry_vehicles = self.get_last_step_geometry_vehicles(geometry_ids)
            vehicle_ids = choices(all_geometry_vehicles, min(n_vehicles, len(all_geometry_vehicles)))
            
        if check_n_vehicles:
            if len(vehicle_ids) != n_vehicles:
                if assert_n_vehicles:
                    desc = "Incident could not be started (could not find enough vehicles, {0} != {1}).".format()
                    raise_error(ValueError, desc, self.curr_step)
                else:
                    if not self._suppress_warnings: raise_warning("Incident could not be started (could not find enough vehicles, {0} != {1}).".format())
                    return False

        if vehicle_ids != None:
            if isinstance(vehicle_ids, str): vehicle_ids = [vehicle_ids]
            elif not isinstance(vehicle_ids, (list, tuple)):
                desc = "Invalid vehicle_ids given '{0}' (must be [str|(str)], not '{1}').".format(vehicle_ids, type(vehicle_ids).__name__)
                raise_error(TypeError, desc, self.curr_step)

            for vehicle_id in vehicle_ids:
                if not self.vehicle_exists(vehicle_id):
                    desc = "Unrecognised vehicle ID given ('{0}').".format(vehicle_id)
                    raise_error(KeyError, desc, self.curr_step)
                elif highlight_vehicles:
                    self.set_vehicle_vals(vehicle_id, highlight=True)

            event_dict["vehicles"]["vehicle_ids"] = vehicle_ids
        
            if edge_speed != None:
                if edge_speed == -1: edge_speed = 15 if self.units.name == "METRIC" else 10
                event_dict["edges"] = {"edge_ids": geometry_ids, "actions": {"max_speed": edge_speed}}

        self.add_events({incident_id: event_dict})
        return True
            
    def vehicle_exists(self, vehicle_id: str) -> bool:
        """
        Tests if a vehicle exists in the network and has departed.
        :return bool: True if ID in list of current vehicle IDs 
        """
        if not isinstance(vehicle_id, str):
            desc = "Invalid vehicle_id given '{0}' (must be 'str', not '{1}').".format(vehicle_id, type(vehicle_id).__name__)
            raise_error(TypeError, desc, self.curr_step)

        return vehicle_id in self._all_curr_vehicle_ids
    
    def junction_exists(self, junction_id: str) -> bool:
        """
        Tests if a junction exists in the network.
        :return bool: True if ID in list of all junction IDs 
        """
        if not isinstance(junction_id, str):
            desc = "Invalid junction_id given '{0}' (must be 'str', not '{1}').".format(junction_id, type(junction_id).__name__)
            raise_error(TypeError, desc, self.curr_step)

        return junction_id in self._all_juncs
    
    def tracked_junction_exists(self, junction_id: str) -> bool:
        """
        Tests if a tracked junction exists in the network.
        :return bool: True if ID in list of tracked junction IDs
        """
        if not isinstance(junction_id, str):
            desc = "Invalid junction_id given '{0}' (must be 'str', not '{1}').".format(junction_id, type(junction_id).__name__)
            raise_error(TypeError, desc, self.curr_step)

        return junction_id in self.tracked_junctions
    
    def tracked_edge_exists(self, edge_id: str) -> bool:
        """
        Tests if a tracked junction exists in the network.
        :return bool: True if ID in list of tracked junction IDs
        """
        if not isinstance(edge_id, str):
            desc = "Invalid edge_id given '{0}' (must be 'str', not '{1}').".format(edge_id, type(edge_id).__name__)
            raise_error(TypeError, desc, self.curr_step)

        return edge_id in self.tracked_edges
    
    def vehicle_loaded(self, vehicle_id: str) -> bool:
        """
        Tests if a vehicle is loaded (may not have departed).
        :return bool: True if ID in list of loaded vehicle IDs
        """
        if not isinstance(vehicle_id, str):
            desc = "Invalid vehicle_id given '{0}' (must be 'str', not '{1}').".format(vehicle_id, type(vehicle_id).__name__)
            raise_error(TypeError, desc, self.curr_step)

        return vehicle_id in self._all_loaded_vehicle_ids
    
    def vehicle_to_depart(self, vehicle_id: str) -> bool:
        """
        Tests if a vehicle is loaded but has not departed yet.
        :return bool: True if vehicle has not departed yet
        """
        if not isinstance(vehicle_id, str):
            desc = "Invalid vehicle_id given '{0}' (must be 'str', not '{1}').".format(vehicle_id, type(vehicle_id).__name__)
            raise_error(TypeError, desc, self.curr_step)
        elif not self.vehicle_loaded(vehicle_id):
            desc = "Vehicle with ID '{0}' has not been loaded.".format(vehicle_id)
            raise_error(KeyError, desc, self.curr_step)
        
        return vehicle_id in self._all_to_depart_vehicle_ids
    
    def add_vehicle_subscriptions(self, vehicle_ids: str|list|tuple, data_keys: str|list|tuple) -> None:
        """
        Creates a new subscription for vehicle variables.
        :param vehicle_ids: List of vehicle IDs or single ID
        :param data_keys:   List of data_keys or single key, from [speed|is_stopped|max_speed|acceleration|position|altitude|heading|edge_id|lane_idx|route_id|route_idx|route_edges]
        """

        if isinstance(data_keys, str): data_keys = [data_keys]
        elif not isinstance(data_keys, (list, tuple)):
            desc = "Invalid data_keys given '{0}' (must be [str|(str)], not '{1}').".format(data_keys, type(data_keys).__name__)
            raise_error(TypeError, desc, self.curr_step)

        if isinstance(vehicle_ids, str): vehicle_ids = [vehicle_ids]
        elif not isinstance(vehicle_ids, (list, tuple)):
            desc = "Invalid vehicle_ids given '{0}' (must be [str|(str)], not '{1}').".format(vehicle_ids, type(vehicle_ids).__name__)
            raise_error(TypeError, desc, self.curr_step)
        
        for vehicle_id in vehicle_ids:
            if self.vehicle_exists(vehicle_id):
                if set(data_keys).issubset(set(traci_constants["vehicle"].keys())):
                    subscription_vars = [traci_constants["vehicle"][data_key] for data_key in data_keys]
                    traci.vehicle.subscribe(vehicle_id, subscription_vars)
                else:
                    unknown_keys = list(set(data_keys) - set(traci_constants["vehicle"].keys()))
                    desc = "Unknown or unsupported data keys [{0}].".format(",".join(unknown_keys))
                    raise_error(KeyError, desc, self.curr_step)
            else:
                desc = "Unrecognised vehicle ID given ('{0}').".format(vehicle_id)
                raise_error(KeyError, desc, self.curr_step)

    def remove_vehicle_subscriptions(self, vehicle_ids: str|list|tuple) -> None:
        """
        Remove all active subscriptions for a vehicle or list of vehicles.
        :param vehicle_ids: List of vehicle IDs or single ID
        """

        if isinstance(vehicle_ids, str): vehicle_ids = [vehicle_ids]
        elif not isinstance(vehicle_ids, (list, tuple)):
            desc = "Invalid vehicle_ids given '{0}' (must be [str|(str)], not '{1}').".format(vehicle_ids, type(vehicle_ids).__name__)
            raise_error(TypeError, desc, self.curr_step)

        for vehicle_id in vehicle_ids:
            if self.vehicle_exists(vehicle_id):
                traci.vehicle.unsubscribe(vehicle_id)
            else:
                desc = "Unrecognised vehicle ID given ('{0}').".format(vehicle_id)
                raise_error(KeyError, desc, self.curr_step)
    
    def add_detector_subscriptions(self, detector_ids: str, data_keys: str|list) -> None:
        """
        Creates a new subscription for detector variables.
        :param detector_id: List of detector IDs or single ID
        :param data_keys:   List of data_keys or single key, from [vehicle_count|vehicle_ids|speed|halting_no|occupancy|last_detection]
        """

        if isinstance(data_keys, str): data_keys = [data_keys]
        elif not isinstance(data_keys, (list, tuple)):
            desc = "Invalid data_keys given '{0}' (must be [str|(str)], not '{1}').".format(data_keys, type(data_keys).__name__)
            raise_error(TypeError, desc, self.curr_step)

        if isinstance(detector_ids, str): detector_ids = [detector_ids]
        elif not isinstance(detector_ids, (list, tuple)):
            desc = "Invalid detector_ids given '{0}' (must be [str|(str)], not '{1}').".format(detector_ids, type(detector_ids).__name__)
            raise_error(TypeError, desc, self.curr_step)

        for detector_id in detector_ids:
            if detector_id not in self.available_detectors.keys():
                desc = "Detector with ID '{0}' not found.".format(detector_id)
                raise_error(KeyError, desc, self.curr_step)
            else:
                detector_type = self.available_detectors[detector_id]["type"]

                match detector_type:
                    case "multientryexit": d_class = traci.multientryexit
                    case "inductionloop": d_class = traci.inductionloop
                    case "_":
                        desc = "Only 'multientryexit' and 'inductionloop' detectors are currently supported (not '{0}').".format(detector_type)
                        raise_error(ValueError, desc, self.curr_step)

            if set(data_keys).issubset(set(traci_constants["detector"].keys())):
                subscription_vars = [traci_constants["detector"][data_key] for data_key in data_keys]
                d_class.subscribe(detector_id, subscription_vars)
            else:
                unknown_keys = list(set(data_keys) - set(traci_constants["detector"].keys()))
                desc = "Unknown or unsupported data keys ['{0}'].".format("', '".join(unknown_keys))
                raise_error(KeyError, desc, self.curr_step)

    def remove_detector_subscriptions(self, detector_ids: str|list|tuple) -> None:
        """
        Remove all active subscriptions for a detector or list of detectors.
        :param detector_ids: List of detector IDs or single ID
        """

        if isinstance(detector_ids, str): detector_ids = [detector_ids]
        elif not isinstance(detector_ids, (list, tuple)):
            desc = "Invalid detector_ids given '{0}' (must be [str|(str)], not '{1}').".format(detector_ids, type(detector_ids).__name__)
            raise_error(TypeError, desc, self.curr_step)

        for detector_id in detector_ids:
            if detector_id not in self.available_detectors.keys():
                desc = "Detector with ID '{0}' not found.".format(detector_id)
                raise_error(KeyError, desc, self.curr_step)
            else:
                detector_type = self.available_detectors[detector_id]["type"]

                match detector_type:
                    case "multientryexit": d_class = traci.multientryexit
                    case "inductionloop": d_class = traci.inductionloop
                    case "_":
                        desc = "Only 'multientryexit' and 'inductionloop' detectors are currently supported (not '{0}').".format(detector_type)
                        raise_error(ValueError, desc, self.curr_step)

                d_class.unsubscribe(detector_id)
    
    def add_geometry_subscriptions(self, geometry_ids: str, data_keys: str|list) -> None:
        """
        Creates a new subscription for geometry (edge/lane) variables.
        :param geometry_ids: List of geometry IDs or single ID
        :param data_keys:    List of data_keys or single key, from [vehicle_count|vehicle_ids|vehicle_speed|halting_no|occupancy]
        """

        if isinstance(data_keys, str): data_keys = [data_keys]
        elif not isinstance(data_keys, (list, tuple)):
            desc = "Invalid data_keys given '{0}' (must be [str|(str)], not '{1}').".format(data_keys, type(data_keys).__name__)
            raise_error(TypeError, desc, self.curr_step)

        if isinstance(geometry_ids, str): geometry_ids = [geometry_ids]
        elif not isinstance(geometry_ids, (list, tuple)):
            desc = "Invalid geometry_ids given '{0}' (must be [str|(str)], not '{1}').".format(geometry_ids, type(geometry_ids).__name__)
            raise_error(TypeError, desc, self.curr_step)

        for geometry_id in geometry_ids:
            g_name = self.geometry_exists(geometry_id)
            if g_name == "edge": g_class = traci.edge
            elif g_name == "lane": g_class = traci.lane
            else:
                desc = "Geometry ID '{0}' not found.".format(geometry_id)
                raise_error(KeyError, desc, self.curr_step)

            if set(data_keys).issubset(set(traci_constants["geometry"].keys())):
                subscription_vars = [traci_constants["geometry"][data_key] for data_key in data_keys]
                g_class.subscribe(geometry_id, subscription_vars)
            else:
                unknown_keys = list(set(data_keys) - set(traci_constants["geometry"].keys()))
                desc = "Unknown or unsupported data keys ['{0}'].".format("', '".join(unknown_keys))
                raise_error(KeyError, desc, self.curr_step)

    def remove_geometry_subscriptions(self, geometry_ids: str|list|tuple) -> None:
        """
        Remove all active subscriptions for a geometry object or list of geometry objects.
        :param geometry_ids: List of geometry IDs or single ID
        """

        if isinstance(geometry_ids, str): geometry_ids = [geometry_ids]
        elif not isinstance(geometry_ids, (list, tuple)):
            desc = "Invalid geometry_ids given '{0}' (must be [str|(str)], not '{1}').".format(geometry_ids, type(geometry_ids).__name__)
            raise_error(TypeError, desc, self.curr_step)

        for geometry_id in geometry_ids:
            g_name = self.geometry_exists(geometry_id)
            if g_name == "edge": g_class = traci.edge
            elif g_name == "lane": g_class = traci.lane
            else:
                desc = "Geometry ID '{0}' not found.".format(geometry_id)
                raise_error(KeyError, desc, self.curr_step)

            g_class.unsubscribe(geometry_id)
    
    def set_vehicle_vals(self, vehicle_ids: list|tuple|str, **kwargs) -> None:
        """
        Calls the TraCI API to change a vehicle's state.
        :param vehicle_ids:  Vehicle ID or list of IDs
        :param colour:       Sets vehicle colour [str|(int)]
        :param highlight:    Highlights the vehicle with a circle (bool)
        :param speed:        Set new speed value [int|float]
        :param max_speed:    Set new max speed value [int|float]
        :param acceleration: Set acceleration for a given duration ([int|float], [int|float])
        :param lane_idx:     Try and change lane for a given duration (int, [int|float])
        :param destination:  Set vehicle destination edge ID [str]
        :param route_id:     Set vehicle route by route ID or list of edges (str)
        :param route_edges:  Set vehicle route by list of edges ([str])
        :param speed_safety_checks: (Indefinitely) set whether speed/acceleration safety constraints are followed when setting speed (bool)
        :param lc_safety_checks: (Indefinitely) set whether lane changing safety constraints are followed when changing lane (bool)
        """

        if isinstance(vehicle_ids, str): vehicle_ids = [vehicle_ids]
        elif not isinstance(vehicle_ids, (list, tuple)):
            desc = "Invalid vehicle_ids given '{0}' (must be [str|(str)], not '{1}').".format(vehicle_ids, type(vehicle_ids).__name__)
            raise_error(TypeError, desc, self.curr_step)

        for vehicle_id in vehicle_ids:
            if not self.vehicle_exists(vehicle_id):
                desc = "Unrecognised vehicle ID given ('{0}').".format(vehicle_id)
                raise_error(KeyError, desc, self.curr_step)
            
            for command, value in kwargs.items():
                match command:
                    case "colour":
                        if value != None:
                            colour = value
                            if isinstance(colour, str):
                                if "#" in colour: colour = colour.lstrip("#")
                                if len(colour) != 6:
                                    desc = "({0}): '{1}' is not a valid hex colour.".format(command, colour)
                                    raise_error(ValueError, desc, self.curr_step)
                                colour = tuple(int(colour[i:i+2], 16) for i in (0, 2, 4))
                            elif not isinstance(colour, (list, tuple)):
                                desc = "({0}): Invalid colour (must be [str|list|tuple], not '{1}').".format(command, type(colour).__name__)
                                raise_error(TypeError, desc, self.curr_step)
                            elif len(colour) not in [3, 4] or all(x > 255 for x in colour) or all(x < 0 for x in colour):
                                desc = "({0}): '{1}' is not a valid RGB or RGBA colour.".format(command, colour)
                                raise_error(ValueError, desc, self.curr_step)
                            
                            if len(colour) == 3: colour = list(colour) + [255]

                            traci.vehicle.setColor(vehicle_id, colour)
                        else:
                            vehicle_type = self.get_vehicle_vals(vehicle_id, "type")
                            type_colour = tuple(traci.vehicletype.getColor(vehicle_type))
                            traci.vehicle.setColor(vehicle_id, type_colour)
                    
                    case "highlight":
                        if isinstance(value, bool):
                            if value: traci.vehicle.highlight(vehicle_id)
                            else: traci.vehicle.highlight(vehicle_id, color=(0, 0, 0, 0))
                        else:
                            desc = "({0}): Invalid speed_safety_checks value '{1}' (must be (str), not '{2}').".format(command, value, type(value).__name__)
                            raise_error(TypeError, desc, self.curr_step)

                    case "speed":
                        if isinstance(value, (int, float)): 
                            units = "kmph" if self.units.name == "METRIC" else "mph"
                            traci.vehicle.setSpeed(vehicle_id, convert_units(value, units, "m/s"))
                        else:
                            desc = "({0}): Invalid speed value '{1}' (must be [int|float], not '{2}').".format(command, value, type(value).__name__)
                            raise_error(TypeError, desc, self.curr_step)
                    
                    case "max_speed":
                        if isinstance(value, (int, float)):
                            units = "kmph" if self.units.name == "METRIC" else "mph"
                            traci.vehicle.setMaxSpeed(vehicle_id, convert_units(value, units, "m/s"))
                        else:
                            desc = "({0}): Invalid max_speed value '{1}' (must be [int|float], not '{2}').".format(command, value, type(value).__name__)
                            raise_error(TypeError, desc, self.curr_step)
                    
                    case "acceleration":
                        if isinstance(value, (list, tuple)) and len(value) == 2:
                            if not isinstance(value[0], (int, float)):
                                desc = "({0}): Invalid acceleration '{1}' (must be [int|float], not '{2}').".format(command, value[0], type(value[0]).__name__)
                                raise_error(TypeError, desc, self.curr_step)
                            if not isinstance(value[1], (int, float)):
                                desc = "({0}): Invalid duration '{1}' (must be [int|float], not '{2}').".format(command, value[1], type(value[1]).__name__)
                                raise_error(TypeError, desc, self.curr_step)
                            traci.vehicle.setAcceleration(vehicle_id, float(value[0]), float(value[1]))
                        else:
                            desc = "({0}): '{0}' requires 2 parameters (acceleration [int|float], duration [int|float])".format(command)
                            raise_error(TypeError, desc, self.curr_step)

                    case "lane_idx":
                        if isinstance(value, (list, tuple)) and len(value) == 2:
                            if not isinstance(value[0], int):
                                desc = "({0}): Invalid lane_idx '{1}' (must be int, not '{2}').".format(command, value[0], type(value[0]).__name__)
                                raise_error(TypeError, desc, self.curr_step)
                            if not isinstance(value[1], (int, float)):
                                desc = "({0}): Invalid duration '{1}' (must be [int|float], not '{2}').".format(command, value[1], type(value[1]).__name__)
                                raise_error(TypeError, desc, self.curr_step)
                            traci.vehicle.changeLane(vehicle_id, value[0], float(value[1]))
                        else:
                            desc = "({0}): '{0}' requires 2 parameters (lane_idx [int], duration [int|float])".format(command)
                            raise_error(TypeError, desc, self.curr_step)

                    case "destination":
                        if isinstance(value, str):
                            if value not in self._all_edges:
                                desc = "({0}): Edge ID '{1}' not found.".format(command, value)
                                raise_error(KeyError, desc, self.curr_step)
                            traci.vehicle.changeTarget(vehicle_id, value)
                        else:
                            desc = "({0}): Invalid edge_id '{1}' (must be str, not '{2}').".format(command, value, type(value).__name__)
                            raise_error(TypeError, desc, self.curr_step)
                    
                    case "route_id":
                        if isinstance(value, str):
                            if value not in self._all_routes.keys():
                                desc = "({0}): Route ID '{1}' not found.".format(command, value)
                                raise_error(KeyError, desc, self.curr_step)
                            traci.vehicle.setRouteID(vehicle_id, value)
                        else:
                            desc = "({0}): Invalid route_id value '{1}' (must be str, not '{2}').".format(command, value, type(value).__name__)
                            raise_error(TypeError, desc, self.curr_step)
                    
                    case "route_edges":
                        if isinstance(value, (list, tuple)) and all(isinstance(x, str) for x in value):
                            for e_id in value:
                                if e_id not in self._all_edges:
                                    desc = "({0}): Edge ID '{1}' in route edges not found.".format(command, e_id)
                                    raise_error(KeyError, desc, self.curr_step)
                            traci.vehicle.setRoute(vehicle_id, value)
                        else:
                            desc = "({0}): Invalid route_egdes value '{1}' (must be (str), not '{2}').".format(command, value, type(value).__name__)
                            raise_error(TypeError, desc, self.curr_step)

                    case "speed_safety_checks":
                        if isinstance(value, bool):
                            if value: traci.vehicle.setSpeedMode(vehicle_id, 31)
                            else: traci.vehicle.setSpeedMode(vehicle_id, 32)
                        elif isinstance(value, int):
                            traci.vehicle.setSpeedMode(vehicle_id, value)
                        else:
                            desc = "({0}): Invalid speed_safety_checks value '{1}' (must be (str), not '{2}').".format(command, value, type(value).__name__)
                            raise_error(TypeError, desc, self.curr_step)

                    case "lc_safety_checks":
                        if isinstance(value, bool):
                            if value: traci.vehicle.setLaneChangeMode(vehicle_id, 1621)
                            else: traci.vehicle.setLaneChangeMode(vehicle_id, 1617)
                        elif isinstance(value, int):
                            traci.vehicle.setLaneChangeMode(vehicle_id, value)
                        else:
                            desc = "({0}): Invalid speed_safety_checks value '{1}' (must be (str), not '{2}').".format(command, value, type(value).__name__)
                            raise_error(TypeError, desc, self.curr_step)

                    case _:
                        desc = "Unrecognised command ('{0}').".format(command)
                        raise_error(AttributeError, desc, self.curr_step)

    def get_vehicle_ids(self, vehicle_types: str|list|tuple|None = None) -> list:
        """
        Return list of IDs for all vehicles currently in the simulation.
        :return list: All current vehicle IDs
        """

        if vehicle_types == None:
            return list(self._all_curr_vehicle_ids)
        else:
            if isinstance(vehicle_types, str): vehicle_types = [vehicle_types]
            elif not isinstance(vehicle_types, (list, tuple)):
                desc = "Invalid vehicle types value '{0}' (must be [str|(str)], not '{1}').".format(vehicle_types, type(vehicle_types).__name__)
                raise_error(TypeError, desc, self.curr_step)
            else:
                for vehicle_type in vehicle_types:
                    if not self.vehicle_type_exists(vehicle_type):
                        desc = "Vehicle type ID '{0}' not found.".format(vehicle_type, type(vehicle_type).__name__)
                        raise_error(TypeError, desc, self.curr_step)
            
            vehicle_ids = []
            for vehicle_id in list(self._all_curr_vehicle_ids):
                if self.get_vehicle_vals(vehicle_id, "type") in vehicle_types: vehicle_ids.append(vehicle_id)

            return vehicle_ids
        
    def get_junction_ids(self) -> list:
        """
        Return list of all junctions in the network.
        :return list: All junction IDs
        """
        return list(self._all_juncs)
    
    def get_tracked_junction_ids(self) -> list:
        """
        Return list of all tracked junctions in the network.
        :return list: All tracked junction IDs
        """
        return list(self.tracked_junctions.keys())
    
    def get_tracked_edge_ids(self) -> list:
        """
        Return list of all tracked edges in the network.
        :return list: All tracked edges IDs
        """
        return list(self.tracked_edges.keys())
        
    def get_vehicle_types(self) -> list:
        """
        Return list of all valid vehicle type IDs.
        :return list: All vehicle type IDs
        """
        return list(self._all_vehicle_types)
    
    def get_geometry_ids(self, geometry_types: str|list|tuple|None = None) -> list:
        """
        Return list of IDs for all edges and lanes in the network.
        :param geometry_types: Geometry type ['EDGE'|'LANE'] or list of types
        :return list:          All geometry types (of type)
        """
        valid_types = ["edge", "lane"]

        if geometry_types == None: geometry_types = valid_types
        elif isinstance(geometry_types, str): geometry_types = [geometry_types]
        elif not isinstance(geometry_types, (list, tuple)):
            desc = "Invalid geometry types value '{0}' (must be [str|(str)], not '{1}').".format(geometry_types, type(geometry_types).__name__)
            raise_error(TypeError, desc, self.curr_step)

        if len(set(geometry_types) - set(valid_types)) != 0:
            desc = "Invalid geometry types (must be 'EDGE' and/or 'LANE')."
            raise_error(ValueError, desc, self.curr_step)
        else: geometry_types = [g_type.upper() for g_type in geometry_types]

        geometry_ids = []
        if "edge" in geometry_types:
            geometry_ids += list(self._all_edges)
        if "lane" in geometry_types:
            geometry_ids += list(self._all_lanes)
        
        return geometry_ids

    def get_detector_ids(self, detector_types: str|list|tuple|None = None) -> list:
        """
        Return list of IDs for all edges and lanes in the network.
        :param detector_types: Detector type ['multientryexit'|'inductionloop'] or list of types
        :return list:          All detector IDs (of type)
        """
        valid_types = ["multientryexit", "inductionloop"]

        if detector_types == None: detector_types = valid_types
        elif isinstance(detector_types, str): detector_types = [detector_types]
        elif not isinstance(detector_types, (list, tuple)):
            desc = "Invalid route egdes value '{0}' (must be [str|(str)], not '{1}').".format(detector_types, type(detector_types).__name__)
            raise_error(TypeError, desc, self.curr_step)
            
        if len(set(detector_types) - set(valid_types)) != 0:
            desc = "Invalid detector types (must be 'multientryexit' and/or 'inductionloop')."
            raise_error(ValueError, desc, self.curr_step)

        detector_ids = []
        for det_id, det_info in self.available_detectors.items():
            if det_info["type"] in detector_types: detector_ids.append(det_id)
        
        return detector_ids

    def get_vehicle_vals(self, vehicle_ids: list|tuple|str, data_keys: str|list) -> dict|str|int|float|list:
        """
        Get data values for specific vehicle using a list of data keys.
        :param vehicle_ids: Vehicle ID or list of IDs
        :param data_keys:   List of keys from [type|length|speed|is_stopped|max_speed|acceleration|position|altitude|heading|departure|edge_id|lane_idx|origin|destination|route_id|route_idx|route_edges], or single key
        :return dict:       Values by data_key (or single value)
        """

        all_data_vals = {}
        if isinstance(vehicle_ids, str): vehicle_ids = [vehicle_ids]
        elif not isinstance(vehicle_ids, (list, tuple)):
            desc = "Invalid vehicle_ids given '{0}' (must be [str|(str)], not '{1}').".format(vehicle_ids, type(vehicle_ids).__name__)
            raise_error(TypeError, desc, self.curr_step)

        for vehicle_id in vehicle_ids:
            if not self.vehicle_exists(vehicle_id):
                desc = "Unrecognised vehicle ID given ('{0}').".format(vehicle_id)
                raise_error(KeyError, desc, self.curr_step)

            return_val = False
            if isinstance(data_keys, str):
                data_keys = [data_keys]
                return_val = True
            elif isinstance(data_keys, (list, tuple)):
                return_val = len(data_keys) == 1
            else:
                desc = "Invalid data_keys given '{0}' (must be [str|(str)], not '{1}').".format(data_keys, type(data_keys).__name__)
                raise_error(TypeError, desc, self.curr_step)
            
            data_vals, vehicle_known = {}, vehicle_id in self._known_vehicles.keys()
            if not vehicle_known: self._known_vehicles[vehicle_id] = {}

            subscribed_data = traci.vehicle.getSubscriptionResults(vehicle_id)
            for data_key in data_keys:
                match data_key:
                    case "type":
                        new_request = not (vehicle_known and data_key in self._known_vehicles[vehicle_id].keys())
                        if new_request: self._known_vehicles[vehicle_id][data_key] = traci.vehicle.getTypeID(vehicle_id)
                        data_vals[data_key] = self._known_vehicles[vehicle_id][data_key]

                    case "length":
                        new_request = not (vehicle_known and data_key in self._known_vehicles[vehicle_id].keys())
                        if new_request:
                            length = traci.vehicle.getLength(vehicle_id)
                            units = "feet" if self.units.name == "IMPERIAL" else "metres"
                            length = convert_units(length, "metres", units)
                            self._known_vehicles[vehicle_id][data_key] = length
                        data_vals[data_key] = self._known_vehicles[vehicle_id][data_key]

                    case "speed":
                        if tc.VAR_SPEED in subscribed_data: speed = subscribed_data[tc.VAR_SPEED]
                        else: speed = traci.vehicle.getSpeed(vehicle_id)
                        
                        units = "kmph" if self.units.name == "METRIC" else "mph"
                        data_vals[data_key] = convert_units(speed, "m/s", units)

                    case "is_stopped":
                        if tc.VAR_SPEED in subscribed_data: speed = subscribed_data[tc.VAR_SPEED]
                        else: speed = traci.vehicle.getSpeed(vehicle_id)
                        data_vals[data_key] = speed < 0.1

                    case "max_speed":
                        if tc.VAR_MAXSPEED in subscribed_data: max_speed = subscribed_data[tc.VAR_MAXSPEED]
                        else: max_speed = traci.vehicle.getMaxSpeed(vehicle_id)
                        
                        units = "kmph" if self.units.name == "METRIC" else "mph"
                        data_vals[data_key] = convert_units(max_speed, "m/s", units)

                    case "acceleration":
                        if tc.VAR_ACCELERATION in subscribed_data: acceleration = subscribed_data[tc.VAR_ACCELERATION]
                        else: acceleration = traci.vehicle.getAcceleration(vehicle_id)
                        data_vals[data_key] = acceleration

                    case "position":
                        if tc.VAR_POSITION in subscribed_data: position = list(subscribed_data[tc.VAR_POSITION])
                        elif tc.VAR_POSITION3D in subscribed_data: position = list(subscribed_data[tc.VAR_POSITION3D])[:2]
                        else: position = list(traci.vehicle.getPosition3D(vehicle_id))[:2]
                        data_vals[data_key] = tuple(position)

                    case "altitude":
                        if tc.VAR_POSITION3D in subscribed_data: altitude = list(subscribed_data[tc.VAR_POSITION3D])[-1]
                        else: altitude = list(traci.vehicle.getPosition3D(vehicle_id))[-1]
                        data_vals[data_key] = altitude

                    case "heading":
                        if tc.VAR_ANGLE in subscribed_data: heading = subscribed_data[tc.VAR_ANGLE]
                        else: heading = traci.vehicle.getAngle(vehicle_id)
                        data_vals[data_key] = heading

                    case "departure":
                        new_request = not (vehicle_known and data_key in self._known_vehicles[vehicle_id].keys())
                        if new_request: self._known_vehicles[vehicle_id][data_key] = int(traci.vehicle.getDeparture(vehicle_id) / self.step_length)
                        data_vals[data_key] = self._known_vehicles[vehicle_id][data_key]

                    case "edge_id":
                        if tc.VAR_ROAD_ID in subscribed_data: edge_id = subscribed_data[tc.VAR_ROAD_ID]
                        else: edge_id = traci.vehicle.getRoadID(vehicle_id)
                        data_vals[data_key] = edge_id

                    case "lane_idx":
                        if tc.VAR_LANE_INDEX in subscribed_data: lane_idx = subscribed_data[tc.VAR_LANE_INDEX]
                        else: lane_idx = traci.vehicle.getLaneIndex(vehicle_id)
                        data_vals[data_key] = lane_idx

                    case "origin":
                        new_request = not (vehicle_known and data_key in self._known_vehicles[vehicle_id].keys())
                        if new_request: self._known_vehicles[vehicle_id][data_key] = list(traci.vehicle.getRoute(vehicle_id))[0]
                        data_vals[data_key] = self._known_vehicles[vehicle_id][data_key]

                    case "destination":
                        if tc.VAR_ROUTE in subscribed_data: route = subscribed_data[tc.VAR_ROUTE]
                        else: route = list(traci.vehicle.getRoute(vehicle_id))
                        data_vals[data_key] = route[-1]

                    case "route_id":
                        if tc.VAR_ROUTE_ID in subscribed_data: route_id = subscribed_data[tc.VAR_ROUTE_ID]
                        else: route_id = traci.vehicle.getRouteID(vehicle_id)
                        data_vals[data_key] = route_id

                    case "route_idx":
                        if tc.VAR_ROUTE_INDEX in subscribed_data: route_idx = subscribed_data[tc.VAR_ROUTE_INDEX]
                        else: route_idx = list(traci.vehicle.getRouteIndex(vehicle_id))
                        data_vals[data_key] = route_idx

                    case "route_edges":
                        if tc.VAR_ROUTE in subscribed_data: route = subscribed_data[tc.VAR_ROUTE]
                        else: route = list(traci.vehicle.getRoute(vehicle_id))
                        data_vals[data_key] = route

                    case _:
                        desc = "Unrecognised key ('{0}').".format(data_key)
                        raise_error(KeyError, desc, self.curr_step)

            if len(vehicle_ids) == 1:
                if set(data_vals.keys()) != set(data_vals):
                    desc = "Invalid data_keys given (must be from accepted list)."
                    raise_error(ValueError, desc, self.curr_step)
                if return_val: return list(data_vals.values())[0]
                else: return data_vals
            else:
                if return_val: all_data_vals[vehicle_id] = list(data_vals.values())[0]
                else: all_data_vals[vehicle_id] = data_vals

        return all_data_vals
    
    def get_vehicle_data(self, vehicle_ids: str) -> dict:
        """
        Get data for specified vehicle, updating _known_vehicles dict.
        :param vehicle_ids: Vehicle ID or list of IDs
        :return dict:       Vehicle data dictionary, returns None if does not exist in simulation
        """

        all_vehicle_data = {}
        if isinstance(vehicle_ids, str): vehicle_ids = [vehicle_ids]
        elif not isinstance(vehicle_ids, (list, tuple)):
            desc = "Invalid vehicle_ids given '{0}' (must be [str|(str)], not '{1}').".format(vehicle_ids, type(vehicle_ids).__name__)
            raise_error(TypeError, desc, self.curr_step)

        for vehicle_id in vehicle_ids:
            if not self.vehicle_exists(vehicle_id):
                desc = "Unrecognised vehicle ID found ('{0}').".format(vehicle_id)
                raise_error(KeyError, desc, self.curr_step)
            
            static_data_keys = ("type", "length", "departure", "origin")
            dynamic_data_keys = ("speed", "acceleration", "is_stopped", "position", "altitude", "heading", "destination")
            vehicle_data = self.get_vehicle_vals(vehicle_id, dynamic_data_keys)

            if vehicle_id not in self._known_vehicles.keys(): new_vehicle = True
            elif len(set(static_data_keys) - set(self._known_vehicles[vehicle_id].keys())) > 0: new_vehicle = True
            else: new_vehicle = False

            if new_vehicle:
                static_veh_data = self.get_vehicle_vals(vehicle_id, static_data_keys)

                self._known_vehicles[vehicle_id] = {"type":        static_veh_data["type"],
                                                    "longitude":    vehicle_data["position"][0],
                                                    "latitude":     vehicle_data["position"][1],
                                                    "speed":        vehicle_data["speed"],
                                                    "acceleration": vehicle_data["acceleration"],
                                                    "is_stopped":   vehicle_data["is_stopped"],
                                                    "length":       static_veh_data["length"],
                                                    "heading":      vehicle_data["heading"],
                                                    "departure":    static_veh_data["departure"],
                                                    "altitude":     vehicle_data["altitude"],
                                                    "destination":  vehicle_data["destination"],
                                                    "origin":       static_veh_data["origin"],
                                                    "last_seen":    self.curr_step
                                                   }
            else:
                self._known_vehicles[vehicle_id]["speed"]        = vehicle_data["speed"]
                self._known_vehicles[vehicle_id]["acceleration"] = vehicle_data["acceleration"]
                self._known_vehicles[vehicle_id]["is_stopped"]   = vehicle_data["is_stopped"]
                self._known_vehicles[vehicle_id]["longitude"]    = vehicle_data["position"][0]
                self._known_vehicles[vehicle_id]["latitude"]     = vehicle_data["position"][1]
                self._known_vehicles[vehicle_id]["heading"]      = vehicle_data["heading"]
                self._known_vehicles[vehicle_id]["altitude"]     = vehicle_data["altitude"]
                self._known_vehicles[vehicle_id]["destination"]  = vehicle_data["destination"]
                self._known_vehicles[vehicle_id]["last_seen"]    = self.curr_step

            vehicle_data = copy(self._known_vehicles[vehicle_id])
            del vehicle_data['last_seen']

            if len(vehicle_ids) == 1:
                return vehicle_data
            else:
                all_vehicle_data[vehicle_id] = vehicle_data

        return all_vehicle_data

    def get_all_vehicle_data(self, vehicle_types: list = None, all_dynamic_data: bool=True) -> dict:
        """
        Collects aggregated vehicle data (no. vehicles & no. waiting vehicles) and all individual vehicle data.
        :param vehicle_types: Type(s) of vehicles to include
        :param all_dynamic_data: Denotes whether to return all individual static & dynamic vehicle data (returns empty dictionary if false)
        :return dict: no vehicles, no waiting, all vehicle data
        """

        all_vehicle_data = {}
        total_vehicle_data = {"no_vehicles": 0, "no_waiting": 0}

        for vehicle_id in self._all_curr_vehicle_ids:

            # Saving known vehicles reduces calls to TraCI by not
            # fetching already known (& unchanging!) data
            if vehicle_id in self._known_vehicles.keys(): vehicle_type = self._known_vehicles[vehicle_id]["type"]
            else: vehicle_type = traci.vehicle.getTypeID(vehicle_id)

            if vehicle_types is None or (isinstance(vehicle_types, (list, tuple)) and vehicle_type in vehicle_types) or (isinstance(vehicle_types, str) and vehicle_type == vehicle_types):

                if self._get_individual_vehicle_data or all_dynamic_data:
                    vehicle_data = self.get_vehicle_data(vehicle_id)
                    all_vehicle_data[vehicle_id] = vehicle_data
                    if vehicle_data["is_stopped"]: total_vehicle_data["no_waiting"] += 1

                elif self.get_vehicle_vals(vehicle_id, "is_stopped"): total_vehicle_data["no_waiting"] += 1

                total_vehicle_data["no_vehicles"] += 1

        return total_vehicle_data["no_vehicles"], total_vehicle_data["no_waiting"], all_vehicle_data
    
    def get_geometry_vals(self, geometry_ids: str|int, data_keys: str|list) -> dict|str|int|float|list:
        """
        Get data values for specific edge or lane using a list of data keys, from: (edge or lane) vehicle_count,
        vehicle_ids, vehicle_speed, halting_no, vehicle_occupancy, curr_travel_time, ff_travel_time, emissions,
        length, max_speed | (edge only) connected_edges, incoming_edges, outgoing_edges, street_name, n_lanes,
        lane_ids | (lane only) edge_id, n_links, allowed, disallowed, left_lc, right_lc
        :param geometry_ids: Either edge or lane ID or list of edge or lane IDs
        :param data_keys:    List of keys or single key
        :return dict:        Values by data_key (or single value)
        """
        all_data_vals = {}
        if isinstance(geometry_ids, str): geometry_ids = [geometry_ids]
        elif not isinstance(geometry_ids, (list, tuple)):
            desc = "Invalid geometry_ids given '{0}' (must be [str|(str)], not '{1}').".format(geometry_ids, type(geometry_ids).__name__)
            raise_error(TypeError, desc, self.curr_step)

        for geometry_id in geometry_ids:
            g_name = self.geometry_exists(geometry_id)
            if g_name == "edge": g_class = traci.edge
            elif g_name == "lane": g_class = traci.lane
            else:
                desc = "Geometry ID '{0}' not found.".format(geometry_id)
                raise_error(KeyError, desc, self.curr_step)

            return_val = False
            if isinstance(data_keys, str):
                data_keys = [data_keys]
                return_val = True
            elif isinstance(data_keys, (list, tuple)):
                return_val = len(data_keys) == 1
            else:
                desc = "Invalid data_keys given '{0}' (must be [str|(str)], not '{1}').".format(data_keys, type(data_keys).__name__)
                raise_error(TypeError, desc, self.curr_step)
            
            data_vals, subscribed_data = {}, g_class.getSubscriptionResults(geometry_id)
            for data_key in data_keys:
                match data_key:
                    case "vehicle_count":
                        if tc.LAST_STEP_VEHICLE_ID_LIST in subscribed_data: vehicle_count = len(list(subscribed_data[tc.LAST_STEP_VEHICLE_ID_LIST]))
                        elif tc.LAST_STEP_VEHICLE_NUMBER in subscribed_data: vehicle_count = subscribed_data[tc.LAST_STEP_VEHICLE_NUMBER]
                        else: vehicle_count = g_class.getLastStepVehicleNumber(geometry_id)
                        data_vals[data_key] = vehicle_count
                        continue

                    case "vehicle_ids":
                        if tc.LAST_STEP_VEHICLE_ID_LIST in subscribed_data: vehicle_ids = list(subscribed_data[tc.LAST_STEP_VEHICLE_ID_LIST])
                        else: vehicle_ids = g_class.getLastStepVehicleIDs(geometry_id)
                        data_vals[data_key] = list(vehicle_ids)
                        continue

                    case "vehicle_speed":
                        if tc.LAST_STEP_MEAN_SPEED in subscribed_data: vehicle_speed = subscribed_data[tc.LAST_STEP_MEAN_SPEED]
                        else: vehicle_speed = g_class.getLastStepMeanSpeed(geometry_id)

                        units = "kmph" if self.units.name == "METRIC" else "mph"
                        data_vals[data_key] = convert_units(vehicle_speed, "m/s", units)
                        continue
                    
                    case "halting_no":
                        if tc.LAST_STEP_VEHICLE_HALTING_NUMBER in subscribed_data: halting_no = subscribed_data[tc.LAST_STEP_VEHICLE_HALTING_NUMBER]
                        else: halting_no = g_class.getLastStepHaltingNumber(geometry_id)
                        data_vals[data_key] = halting_no
                        continue 

                    case "vehicle_occupancy":
                        if tc.LAST_STEP_OCCUPANCY in subscribed_data: vehicle_occupancy = subscribed_data[tc.LAST_STEP_OCCUPANCY]
                        else: vehicle_occupancy = g_class.getLastStepOccupancy(geometry_id)
                        data_vals[data_key] = vehicle_occupancy
                        continue

                    case "curr_travel_time":
                        data_vals[data_key] = g_class.getTraveltime(geometry_id)
                        continue

                    case "ff_travel_time":
                        length, speed = self.get_geometry_vals(geometry_id, ("length", "max_speed"))
                        if self.units.name == "UK": speed = convert_units(speed, "mph", "kmph")
                        data_vals[data_key] = length / speed

                    case "emissions":
                        data_vals[data_key] = ({"CO2": g_class.getCO2Emission(geometry_id), "CO": g_class.getCO2Emission(geometry_id), "HC": g_class.getHCEmission(geometry_id),
                                                "PMx": g_class.getPMxEmission(geometry_id), "NOx": g_class.getNOxEmission(geometry_id)})
                        continue

                    case "length":
                        if g_name == "edge": geometry = self.network.getEdge(geometry_id)
                        else: geometry = self.network.getLane(geometry_id)
                        length = LineString(geometry.getShape()).length
                        
                        units = "kilometres" if self.units.name == "METRIC" else "miles"
                        data_vals[data_key] = convert_units(length, "metres", units)
                        
                if g_name == "edge":
                    match data_key:
                        
                        case "connected_edges":
                            data_vals[data_key] = {'incoming': [e.getID() for e in self.network.getEdge(geometry_id).getIncoming()],
                                                   'outgoing': [e.getID() for e in self.network.getEdge(geometry_id).getOutgoing()]}
                        case "incoming_edges":
                            data_vals[data_key] = [e.getID() for e in self.network.getEdge(geometry_id).getIncoming()]
                        case "outgoing_edges":
                            data_vals[data_key] = [e.getID() for e in self.network.getEdge(geometry_id).getOutgoing()]
                        case "junction_ids":
                            edge = self.network.getEdge(geometry_id)
                            data_vals[data_key] = [edge.getToNode().getID(), edge.getFromNode().getID()]
                        case "street_name":
                            data_vals[data_key] = g_class.getStreetName(geometry_id)
                        case "n_lanes":
                            data_vals[data_key] = g_class.getLaneNumber(geometry_id)
                        case "lane_ids":
                            n_lanes = g_class.getLaneNumber(geometry_id)
                            data_vals[data_key] = ["{0}_{1}".format(geometry_id, idx) for idx in range(n_lanes)]
                        case "max_speed":
                            n_lanes = g_class.getLaneNumber(geometry_id)
                            lane_ids = ["{0}_{1}".format(geometry_id, idx) for idx in range(n_lanes)]
                            avg_lane_speed = sum([traci.lane.getMaxSpeed(lane_id) for lane_id in lane_ids])/len(lane_ids)

                            units = "kmph" if self.units.name == "METRIC" else "mph"
                            data_vals[data_key] = convert_units(avg_lane_speed, "m/s", units)
                        case _:
                            desc = "Unrecognised key ('{0}').".format(data_key)
                            raise_error(ValueError, desc, self.curr_step)
                elif g_name == "lane":
                    match data_key:
                        case "edge_id":
                            data_vals[data_key] = g_class.getEdgeID(geometry_id)
                        case "n_links":
                            data_vals[data_key] = g_class.getLinkNumber(geometry_id)
                        case "allowed":
                            data_vals[data_key] = g_class.getAllowed(geometry_id)
                        case "disallowed":
                            data_vals[data_key] = g_class.getDisallowed(geometry_id)
                        case "left_lc":
                            data_vals[data_key] = g_class.getChangePermissions(geometry_id, 0)
                        case "right_lc":
                            data_vals[data_key] = g_class.getChangePermissions(geometry_id, 1)
                        case "max_speed":
                            units = "kmph" if self.units.name == "METRIC" else "mph"
                            data_vals[data_key] = convert_units(g_class.getMaxSpeed(geometry_id), "m/s", units)
                        case _:
                            desc = "Unrecognised key ('{0}').".format(data_key)
                            raise_error(ValueError, desc, self.curr_step)

            if len(geometry_ids) == 1:
                if set(data_vals.keys()) != set(data_vals):
                    desc = "Invalid data_keys given (must be from accepted list)."
                    raise_error(ValueError, desc, self.curr_step)
                if return_val: return list(data_vals.values())[0]
                else: return data_vals
            else:
                if return_val: all_data_vals[geometry_id] = list(data_vals.values())[0]
                else: all_data_vals[geometry_id] = data_vals

        return all_data_vals

    def set_geometry_vals(self, geometry_ids: str|int, **kwargs) -> None:
        """
        Calls the TraCI API to change a edge or lane's state.
        :param geometry_ids: Edge or lane ID or list of edge or lane IDs
        :param max_speed:    Set new max speed value [int|float]
        :param allowed:      Set allowed vehicle types [(str)], empty list allows all (lane only)
        :param disallowed:   Set disallowed vehicle types [(str)] (lane only)
        :param left_lc:      Set left lane changing vehicle permission with by vehicle_type list [(str)] (lane only)
        :param right_lc:     Set right lane changing vehicle permission with by vehicle_type list [(str)] (lane only)
        """
        
        if isinstance(geometry_ids, str): geometry_ids = [geometry_ids]
        elif not isinstance(geometry_ids, (list, tuple)):
            desc = "Invalid vehicle_ids given '{0}' (must be [str|(str)], not '{1}').".format(geometry_ids, type(geometry_ids).__name__)
            raise_error(TypeError, desc, self.curr_step)

        for geometry_id in geometry_ids:
            if geometry_id in self._all_edges:   g_class, g_name = traci.edge, "edge"
            elif geometry_id in self._all_lanes: g_class, g_name = traci.lane, "lane"
            else:
                desc = "Unrecognised egde or lane ID given ('{0}').".format(geometry_id)
                raise_error(KeyError, desc, self.curr_step)
            
            for command, value in kwargs.items():
                match command:
                    case "max_speed":
                        if isinstance(value, (int, float)): 
                            if value >= 0.1:
                                units = "kmph" if self.units.name == "METRIC" else "mph"
                                g_class.setMaxSpeed(geometry_id, convert_units(value, units, "m/s"))
                            else:
                                unit = "km/h" if self.units.name == "METRIC" else "mph"
                                desc = "({0}): Invalid speed value '{1}' (must be >= 0.1{2}).".format(command, value, unit)
                                raise_error(ValueError, desc, self.curr_step)
                        else:
                            desc = "({0}): Invalid max_speed value '{1}' (must be [int|float], not '{2}').".format(command, value, type(value).__name__)
                            raise_error(TypeError, desc, self.curr_step)
                    case "allowed":
                        if g_name != "lane":
                            desc = "({0}): Command is only valid for lanes.".format(command)
                            raise_error(ValueError, desc, self.curr_step)
                        if isinstance(value, (list, tuple)):
                            curr_allowed = list(g_class.getAllowed(geometry_id))
                            allowed = tuple(set(curr_allowed + list(value)))
                            g_class.setAllowed(geometry_id, allowed)
                            
                            curr_disallowed = list(g_class.getDisallowed(geometry_id))
                            disallowed = tuple(set(curr_disallowed) - set(value))
                            g_class.setDisallowed(geometry_id, disallowed)
                        else:
                            desc = "({0}): Invalid allowed value '{1}' (must be [str], not '{2}').".format(command, value, type(value).__name__)
                            raise_error(TypeError, desc, self.curr_step)

                    case "disallowed":
                        if g_name != "lane":
                            desc = "({0}): Command is only valid for lanes.".format(command)
                            raise_error(ValueError, desc, self.curr_step)
                        if isinstance(value, (list, tuple)):
                            curr_disallowed = list(g_class.getDisallowed(geometry_id))
                            disallowed = tuple(set(curr_disallowed + list(value)))
                            g_class.setDisallowed(geometry_id, disallowed)
                            
                            curr_allowed = list(g_class.getAllowed(geometry_id))
                            allowed = tuple(set(curr_allowed) - set(value))
                            g_class.setAllowed(geometry_id, allowed)
                        else:
                            desc = "({0}): Invalid disallowed value '{1}' (must be [str], not '{2}').".format(command, value, type(value).__name__)
                            raise_error(TypeError, desc, self.curr_step)

                    case "left_lc":
                        if g_name != "lane":
                            desc = "({0}): Command is only valid for lanes.".format(command)
                            raise_error(ValueError, desc, self.curr_step)
                        if isinstance(value, (list, tuple)):
                            g_class.setChangePermissions(geometry_id, value[0], 1)
                        else:
                            desc = "({0}): Invalid left_lc value '{1}' (must be [str], not '{2}').".format(command, value, type(value).__name__)
                            raise_error(TypeError, desc, self.curr_step)
                    
                    case "right_lc":
                        if g_name != "lane":
                            desc = "({0}): Command is only valid for lanes.".format(command)
                            raise_error(ValueError, desc, self.curr_step)
                        if isinstance(value, (list, tuple)):
                            g_class.setChangePermissions(geometry_id, value[0], -1)
                        else:
                            desc = "({0}): Invalid right_lc value '{1}' (must be [str], not '{2}').".format(command, value, type(value).__name__)
                            raise_error(TypeError, desc, self.curr_step)

                    case _:
                        desc = "Unrecognised command ('{0}').".format(command)
                        raise_error(AttributeError, desc, self.curr_step)
                
    def get_last_step_geometry_vehicles(self, geometry_ids: str|list, vehicle_types: list|None = None, flatten: bool = False) -> dict|list:
        """
        Get the IDs of vehicles on a lane or egde, by geometry ID.
        :param geometry_ids:  Lane or edge ID or list of lane or edge IDs
        :param vehicle_types: Included vehicle types
        :param flatten:       If true, all IDs are returned in a 1D array, else a dict with vehicles for each lane or edge
        :return dict|list:    Dict or list containing all vehicle IDs
        """

        geometry_ids = [geometry_ids] if not isinstance(geometry_ids, list) else geometry_ids
        if len(geometry_ids) == 1: flatten = True
        vehicle_types = [vehicle_types] if vehicle_types != None and not isinstance(vehicle_types, list) else vehicle_types

        vehicle_ids = [] if flatten else {}
        for geometry_id in geometry_ids:

            g_vehicle_ids = self.get_geometry_vals(geometry_id, "vehicle_ids")
            if vehicle_types != None:
                g_vehicle_ids = [vehicle_id for vehicle_id in g_vehicle_ids if self.get_vehicle_vals(vehicle_id, "type") in vehicle_types]

            if flatten: vehicle_ids += g_vehicle_ids
            else: vehicle_ids[geometry_id] = g_vehicle_ids

        if flatten: vehicle_ids = list(set(vehicle_ids))

        return vehicle_ids
    
    def geometry_exists(self, geometry_id: str|int) -> str|None:
        """
        Get geometry type by ID, if geometry with the ID exists.
        :param geometry_id: Lane or edge ID
        :return str|None:   Geometry type, or None if it does not exist.
        """
        if not isinstance(geometry_id, str):
            desc = "Invalid geometry_id given '{0}' (must be 'str', not '{1}').".format(geometry_id, type(geometry_id).__name__)
            raise_error(TypeError, desc, self.curr_step)

        if geometry_id in self._all_edges: return "edge"
        elif geometry_id in self._all_lanes: return "lane"
        else: return None

    def detector_exists(self, detector_id: str) -> str|None:
        """
        Get detector type by ID, if a detector with the ID exists.
        :param detector_id: Detector ID
        :return str|None:   Detector type, or None if it does not exist.
        """
        if not isinstance(detector_id, str):
            desc = "Invalid detector_id given '{0}' (must be 'str', not '{1}').".format(detector_id, type(detector_id).__name__)
            raise_error(TypeError, desc, self.curr_step)

        if detector_id in self.available_detectors.keys():
            return self.available_detectors[detector_id]["type"]
        else: return None

    def route_exists(self, route_id: str) -> str|None:
        """
        Get route edges by ID, if a route with the ID exists.
        :param route_id:  Route ID
        :return str|None: List of route edges, or None if it does not exist.
        """
        if not isinstance(route_id, str):
            desc = "Invalid route_id given '{0}' (must be 'str', not '{1}').".format(route_id, type(route_id).__name__)
            raise_error(TypeError, desc, self.curr_step)

        if route_id in self._all_routes.keys():
            return self._all_routes[route_id]
        else: return None

    def vehicle_type_exists(self, vehicle_type: str) -> bool:
        """
        Get whether vehicle_type exists.
        :param vehicle_type: Vehicle type ID
        :return bool:        Denotes whether vehicle type exists
        """
        if not isinstance(vehicle_type, str):
            desc = "Invalid vehicle_type given '{0}' (must be 'str', not '{1}').".format(vehicle_type, type(vehicle_type).__name__)
            raise_error(TypeError, desc, self.curr_step)

        return vehicle_type in list(self._all_vehicle_types)

    def get_event_ids(self, event_statuses: str|list|tuple|None = None) -> list:
        """
        Return event IDs by status, one or more of 'scheduled', 'active' or 'completed'.
        :param event_statuses: Event status type or list of types
        :return list: List of event IDs
        """
        valid_statuses = ["scheduled", "active", "completed"]
        if isinstance(event_statuses, str): event_statuses = [event_statuses]
        elif event_statuses == None: event_statuses = valid_statuses
        elif not isinstance(event_statuses, (list, tuple)):
            desc = "Invalid event_statuses '{0}' type (must be [str|list|tuple], not '{1}').".format(event_statuses, type(event_statuses).__name__)
            raise_error(TypeError, desc, self.curr_step)
        
        if len(set(event_statuses) - set(valid_statuses)) != 0:
            desc = "Invalid event_statuses (must only include ['scheduled'|'active'|'completed'])."
            raise_error(KeyError, desc, self.curr_step)

        return self._scheduler.get_event_ids(event_statuses)

    def event_exists(self, event_id: str) -> str|None:
        """
        Get whether event with ID event_id exists.
        :param event_id: Event ID
        :return str|None: Returns None if it does not exist, otherwise status ('scheduled'|'active'|'completed')
        """
        if self._scheduler == None: return None
        else: return self._scheduler.get_event_status(event_id)

    def controller_exists(self, controller_id: str) -> str|None:
        """
        Get whether controller with ID controller_id exists.
        :param controller_id: Controller ID
        :return str|None: Returns None if it does not exist, otherwise type ('VSLController'|'RGController')
        """
        if controller_id in self.controllers: return self.controllers[controller_id].__name__()
        else: return None

    def get_controller_ids(self, controller_types: str|list|tuple|None = None) -> list:
        """
        Return list of all controller IDs, or controllers of specified type ('VSLController' or 'RGController').
        :return list: Controller IDs
        """
        valid_types = ["VSLController", "RGController"]
        if isinstance(controller_types, str): controller_types = [controller_types]
        elif controller_types == None: controller_types = valid_types
        elif not isinstance(controller_types, (list, tuple)):
            desc = "Invalid controller_types '{0}' type (must be [str|list|tuple], not '{1}').".format(controller_types, type(controller_types).__name__)
            raise_error(TypeError, desc, self.curr_step)
        
        if len(set(controller_types) - set(valid_types)) != 0:
            desc = "Invalid controller_types (must only include ['VSLController'|'RGController'])."
            raise_error(KeyError, desc, self.curr_step)

        return list([c_id for c_id, c in self.controllers.items() if c.__name__() in controller_types])

    def remove_controllers(self, controller_ids: str|list|tuple) -> None:
        """
        Remove controllers and delete their collected data.
        :param controller_ids: List of controller IDs or single ID
        """

        if isinstance(controller_ids, str): controller_ids = [controller_ids]
        elif not isinstance(controller_ids, (list, tuple)):
            desc = "Invalid controller_ids '{0}' type (must be [str|list|tuple], not '{1}').".format(controller_ids, type(controller_ids).__name__)
            raise_error(TypeError, desc, self.curr_step)

        for controller_id in controller_ids:
            if self.controller_exists(controller_id) != None:
                if self.controllers[controller_id].activated:
                    self.controllers[controller_id].deactivate()
                del self.controllers[controller_id]
            else:
                desc = "Controller with ID '{0}' not found.".format(controller_id)
                raise_error(KeyError, desc, self.curr_step)

    def print_summary(self, save_file=None) -> None:
        """
        Prints a summary of a sim_data file or dictionary, listing
        simulation details, vehicle statistics, detectors, controllers,
        tracked edges/junctions and events. The summary can also be saved
        as a '.txt' file.
        :param save_file: '.txt' filename, if given will be used to save summary
        """
        print_summary(self._all_data, save_file)

    def print_sim_data_struct(self) -> None:
        """
        Prints the structure of the current sim_data dictionary, with keys
        and data types for values. Lists/tuples are displayed at max 2D. '*'
        represents the maximum dimension value if the dimension size is inconsistent,
        and '+' denotes the array dimension is greater than 2.
        """
        
        print_sim_data_struct(self._all_data)

def print_sim_data_struct(sim_data: Simulation|dict|str) -> None:
    """
    Prints the structure of a sim_data dictionary, from a Simulation
    object, dict or filepath, with keys and data types for values. Lists/tuples
    are displayed at max 2D. '*' represents the maximum dimension value if
    the dimension size is inconsistent, and '+' denotes the array dimension is
    greater than 2.
    :param sim_data: Either Simulation object, dictionary or sim_data filepath
    """
    
    if isinstance(sim_data, Simulation):
        dictionary = sim_data.__dict__()
    elif isinstance(sim_data, dict):
        dictionary = sim_data
    elif isinstance(sim_data, str):
        if sim_data.endswith(".json"): r_class, r_mode = json, "r"
        elif sim_data.endswith(".pkl"): r_class, r_mode = pkl, "rb"
        else:
            caller = "{0}()".format(inspect.stack()[0][3])
            desc = "{0}: sim_data file '{1}' is invalid (must be '.json' or '.pkl').".format(caller, sim_data)
            raise ValueError(desc)

        if os.path.exists(sim_data):
            with open(sim_data, r_mode) as fp:
                dictionary = r_class.load(fp)
    else:
        desc = "Invalid sim_data type (must be [Simulation|dict|str, not '{0}'])".format(type(sim_data).__name__)
        raise_error(TypeError, desc)

    _print_dict({dictionary["scenario_name"]: dictionary})

def _print_dict(dictionary, indent=0, prev_indent="", prev_key=None):
    dict_keys = list(dictionary.keys())
    for key in dict_keys:
        val, is_last = dictionary[key], key == dict_keys[-1]
        curr_indent = _get_indent(indent, is_last, prev_indent)
        if isinstance(val, dict) and prev_key != "trips":
            print(curr_indent+key+":")
            _print_dict(val, indent+1, curr_indent, key)
        else:
            if isinstance(val, (list, tuple, dict)):
                type_str = type(val).__name__ + " " + _get_2d_shape(val)
            else:
                type_str = type(val).__name__
                
            print("{0}{1}: {2}".format(curr_indent, key, type_str))
        prev_indent = curr_indent
    
def _get_indent(indent_no, last, prev_indent, col_width=6):
    if indent_no == 0: return ""
    else:
        v_connector = "|{0}".format(" "*(col_width-1))
        end = "─- "

        connector = "└" if last else "├"
        indent_str = "  "+v_connector*(indent_no-1) + connector + end
        indent_arr, prev_indent = [*indent_str], [*prev_indent]

        for idx, _ in enumerate(indent_arr):
            if idx < len(prev_indent):
                prev_char = prev_indent[idx]
                if prev_char in [" ", "└"]: indent_arr[idx] = " "
                elif prev_char in ["|"]: indent_arr[idx] = "|"
                elif prev_char == "├" and indent_arr[idx] not in ["├", "└"]: indent_arr[idx] = "|"

        indent_str = "".join(indent_arr)
        return indent_str
    
def _get_2d_shape(array):

    x = len(array)
    arrs = []
    deeper = False
    for elem in array:
        if isinstance(elem, (list, tuple)):
            arrs.append(len(elem))
            deeper = deeper or True in [isinstance(elem2, (list, tuple)) for elem2 in elem]

    if len(arrs) > 0:
        if len(set(arrs)) == 1:
            return "({0}x{1})".format(x, arrs[0])
        else:
            return_str = "({0}x{1}*)".format(x, max(arrs))
            if deeper: return_str += "+"
            return return_str
    else: return "(1x{0})".format(x)

class TrackedJunction:
    def __init__(self, junc_id: str|int, sim: Simulation, junc_params: dict|str=None) -> None:
        self.id = junc_id
        self.position = traci.junction.getPosition(junc_id)

        self.sim = sim
        self.init_time = sim.curr_step
        self.curr_time = sim.curr_step

        self.track_flow = False
        self.measure_spillback = False
        self.measure_queues = False
        self.is_meter = False
        self.has_tl = junc_id in sim._all_tls

        if self.has_tl:
            state_str = traci.trafficlight.getRedYellowGreenState(junc_id)
            self.m_len = len(state_str)
            self.states, self.curr_state = [], []        
            self.durations = [[] for _ in range(self.m_len)]
            self.avg_green, self.avg_m_red = 0, 0
            self.avg_m_green, self.avg_m_red = [0 for _ in range(self.m_len)], [0 for _ in range(self.m_len)]

        if junc_params != None:
            junc_params = load_params(junc_params, "junc_params", step=self.curr_time)

            valid_params = {"flow_params": dict, "meter_params": dict}
            error, desc = test_input_dict(junc_params, valid_params, "'{0}' junction".format(self.id))
            if error != None: raise_error(error, desc, self.sim.curr_step)

            if "flow_params" in junc_params.keys():
                flow_params = junc_params["flow_params"]

                valid_params = {"inflow_detectors": (list, tuple), "outflow_detectors": (list, tuple), "vehicle_types": list}
                error, desc = test_input_dict(flow_params, valid_params, "'{0}' flow".format(self.id), required=["inflow_detectors", "outflow_detectors"])
                if error != None: raise_error(error, desc, self.sim.curr_step)

                if "inflow_detectors" in flow_params.keys() or "outflow_detectors" in flow_params.keys():
                    if not ("inflow_detectors" in flow_params.keys() and "outflow_detectors" in flow_params.keys()):
                        desc = "Both 'inflow_detectors' and 'outflow_detectors' are required parameters to track flow (Junction ID: '{0}').".format(self.id)
                        raise_error(KeyError, desc, self.sim.curr_step)
                    else:

                        for detector_id in flow_params["inflow_detectors"]:
                            if detector_id not in self.sim.available_detectors.keys():
                                desc = "Unrecognised detector ID '{0}' given in inflow_detectors (Junction ID: '{1}').".format(detector_id, self.id)
                                raise_error(KeyError, desc, self.sim.curr_step)
                        for detector_id in flow_params["outflow_detectors"]:
                            if detector_id not in self.sim.available_detectors.keys():
                                desc = "Unrecognised detector ID '{0}' given in outflow_detectors (Junction ID: '{1}').".format(detector_id, self.id)
                                raise_error(KeyError, desc, self.sim.curr_step)

                        self.inflow_detectors = flow_params["inflow_detectors"]
                        self.outflow_detectors = flow_params["outflow_detectors"]

                    if "vehicle_types" in flow_params.keys(): self.flow_vtypes = ["all"] + flow_params["vehicle_types"]
                    else: self.flow_vtypes = ["all"]
                    
                    self.v_in, self.v_out = {vehicle_type: [] for vehicle_type in self.flow_vtypes}, {vehicle_type: [] for vehicle_type in self.flow_vtypes}
                    self.inflows, self.outflows = {vehicle_type: [] for vehicle_type in self.flow_vtypes}, {vehicle_type: [] for vehicle_type in self.flow_vtypes}

                    self.track_flow = True

            if "meter_params" in junc_params.keys():
                meter_params = junc_params["meter_params"]

                valid_params = {"min_rate": (int, float), "max_rate": (int, float), "ramp_edges": (list, tuple),
                                "queue_detector": str, "init_rate": (int, float)}
                error, desc = test_input_dict(meter_params, valid_params, "'{0}' meter".format(self.id), required=["min_rate", "max_rate"])
                if error != None: raise_error(error, desc, self.sim.curr_step)

                self.is_meter = True
                self.min_rate, self.max_rate = meter_params["min_rate"], meter_params["max_rate"]

                self.metering_rates = []
                self.rate_times = []

                self.queue_detector = None
                self.ramp_edges = None

                self.queue_lengths, self.queue_delays = [], []

                if "ramp_edges" in meter_params.keys():
                    self.ramp_edges = meter_params["ramp_edges"]

                    for edge in self.ramp_edges:
                        if edge not in self.sim._all_edges:
                            desc = "Edge ID '{0}' not found.".format(edge)
                            raise_error(KeyError, desc, self.sim.curr_step)

                    self.measure_spillback, self.spillback_vehs = True, []
                    self.measure_queues, self.queue_detector = True, None
                    self.curr_queuing = set([])

                if not self.measure_queues:
                    if "queue_detector" in meter_params.keys():
                        self.measure_queues, self.queue_detector = True, meter_params["queue_detector"]

                        if self.queue_detector not in self.sim.available_detectors.keys():
                            desc = "Unrecognised detector ID given as queue_detector ('{0}').".format(self.queue_detector)
                            raise_error(KeyError, desc, self.sim.curr_step)
                        elif self.sim.available_detectors[self.queue_detector]["type"] != "multientryexit":
                            desc = "Only 'multientryexit' detectors can be used to find queue length (not '{0}').".format(self.sim.available_detectors[self.queue_detector]["type"])
                            raise_error(ValueError, desc, self.sim.curr_step)

                if "init_rate" in meter_params.keys(): self.sim.set_tl_metering_rate(self.id, meter_params["init_rate"])
                else: self.sim.set_tl_metering_rate(self.id, self.max_rate)

            else: self.is_meter = False
    
    def __str__(self): return "<TrackedJunction: '{0}'>".format(self.id)
    def __name__(self): return "TrackedJunction"

    def __dict__(self) -> dict:
        """
        Returns the current state of junction data as a dictionary.
        :return dict: TrackedJunction data dictionary
        """

        junc_dict = {"position": self.position, "init_time": self.init_time, "curr_time": self.curr_time}
        
        if self.has_tl: junc_dict["tl"] = {"m_len": self.m_len, "avg_green": self.avg_green, "avg_red": self.avg_red,
                                           "avg_m_green": self.avg_m_green, "avg_m_red": self.avg_m_red, "m_phases": self.durations}

        if self.track_flow:
            junc_dict["flows"] = {"inflow_detectors": self.inflow_detectors, "outflow_detectors": self.outflow_detectors,
                                 "all_inflows": self.inflows, "all_outflows": self.outflows}
            
        if self.is_meter:
            junc_dict["meter"] = {"metering_rates": self.metering_rates, "rate_times": self.rate_times}
            
            if self.measure_queues:
                junc_dict["meter"]["queue_lengths"] = self.queue_lengths
                junc_dict["meter"]["queue_delays"] = self.queue_delays

            if self.measure_spillback:
                junc_dict["meter"]["spillback_vehs"] = self.spillback_vehs

            junc_dict["meter"]["min_rate"] = self.min_rate
            junc_dict["meter"]["max_rate"] = self.max_rate

        return junc_dict

    def reset(self) -> None:
        """
        Resets junction data collection.
        """
        
        self.init_time = self.sim.curr_step
        self.curr_time = self.sim.curr_step

        if self.has_tl:
            self.states = []
            self.durations = [[] for _ in range(self.m_len)]
            self.avg_green, self.avg_m_red = 0, 0
            self.avg_m_green, self.avg_m_red = [0 for _ in range(self.m_len)], [0 for _ in range(self.m_len)]

        if self.track_flow:
            self.v_in, self.v_out = {vehicle_type: [] for vehicle_type in self.flow_vtypes}, {vehicle_type: [] for vehicle_type in self.flow_vtypes}
            self.inflows, self.outflows = {vehicle_type: [] for vehicle_type in self.flow_vtypes}, {vehicle_type: [] for vehicle_type in self.flow_vtypes}

        if self.is_meter:
            self.metering_rates = []
            self.rate_times = []

            if self.measure_queues:
                self.queue_lengths = []
                self.queue_delays = []

            if self.measure_spillback:
                self.spillback_vehs = []

    def update(self) -> None:
        """
        Update junction flow and TL data for the current time step.
        """

        self.curr_time = self.sim.curr_step
        
        if self.has_tl:
            curr_state = traci.trafficlight.getRedYellowGreenState(self.id)
            colours = [*curr_state]
            for idx, mc in enumerate(colours):
                
                if len(self.durations[idx]) == 0 or mc.upper() != self.durations[idx][-1][0]:
                    self.durations[idx].append([mc.upper(), 1])
                elif mc.upper() == self.durations[idx][-1][0]:
                    self.durations[idx][-1][1] = self.durations[idx][-1][1] + 1

                if mc.upper() == 'G':
                    m_green_durs = [val[1] for val in self.durations[idx] if val[0] == 'G']
                    self.avg_m_green[idx] = sum(m_green_durs) / len(m_green_durs)
                elif mc.upper() == 'R':
                    m_red_durs = [val[1] for val in self.durations[idx] if val[0] == 'R']
                    self.avg_m_red[idx] = sum(m_red_durs) / len(m_red_durs)

            self.avg_green = sum(self.avg_m_green) / len(self.avg_m_green)
            self.avg_red = sum(self.avg_m_red) / len(self.avg_m_red)

            self.states.append(colours)
            self.curr_state = colours

        if self.track_flow:
            
            for vehicle_type in self.flow_vtypes:
                new_v_in = self.sim.get_last_step_detector_vehicles(self.inflow_detectors, vehicle_types=[vehicle_type] if vehicle_type != "all" else None, flatten=True)
                new_v_in = list(set(new_v_in) - set(self.v_in[vehicle_type]))
                self.v_in[vehicle_type] += new_v_in
                self.inflows[vehicle_type].append(len(new_v_in))

            for vehicle_type in self.flow_vtypes:
                new_v_out = self.sim.get_last_step_detector_vehicles(self.outflow_detectors, vehicle_types=[vehicle_type] if vehicle_type != "all" else None, flatten=True)
                new_v_out = list(set(new_v_out) - set(self.v_out[vehicle_type]))
                self.v_out[vehicle_type] += new_v_out
                self.outflows[vehicle_type].append(len(new_v_out))

        if self.measure_queues:

            if self.ramp_edges != None:
                queuing_vehicles = self.sim.get_last_step_geometry_vehicles(self.ramp_edges, flatten=True)
                self.queue_lengths.append(len(queuing_vehicles))

                num_stopped = len([veh_id for veh_id in queuing_vehicles if self.sim.get_vehicle_vals(veh_id, "is_stopped")])
                self.queue_delays.append(num_stopped * self.sim.step_length)
            
            elif self.queue_detector != None:
                queuing_vehicles = self.sim.get_last_step_detector_vehicles(self.queue_detector, flatten=True)
                self.queue_lengths.append(len(queuing_vehicles))

                num_stopped = len([veh_id for veh_id in queuing_vehicles if self.sim.get_vehicle_vals(veh_id, "is_stopped")])
                self.queue_delays.append(num_stopped * self.sim.step_length)

            else:
                desc = "Cannot update queue length (no detector or entry/exit edges)"
                raise_error(KeyError, desc, self.sim.curr_step)

        if self.measure_spillback:
            spillback_vehs, all_waiting_vehs = 0, 0
            all_loaded_vehicles = self.sim._all_loaded_vehicle_ids
            for veh_id in all_loaded_vehicles:
                if not self.sim.vehicle_departed(veh_id):
                    if traci.vehicle.getRoute(veh_id)[0] == self.ramp_edges[0]:
                        spillback_vehs += 1
                    all_waiting_vehs += 1

            self.spillback_vehs.append(spillback_vehs)

class TrackedEdge:
    def __init__(self, edge_id: str, simulation: Simulation) -> None:
        self.id = edge_id
        self.sim = simulation

        self.init_time = self.sim.curr_step
        self.curr_time = self.sim.curr_step

        edge = self.sim.network.getEdge(edge_id)

        self.linestring = edge.getShape()
        self.line = LineString(self.linestring)
        self.length_unit = "miles" if self.sim.units.name == "IMPERIAL" else "kilometres"
        self.length = convert_units(self.line.length, "metres", self.length_unit)

        self.n_lanes = self.sim.get_geometry_vals(self.id, "n_lanes")

        self.to_node = edge.getToNode().getID()
        self.from_node = edge.getFromNode().getID()

        self.step_vehicles = []

        self.sim.add_geometry_subscriptions(self.id, "vehicle_ids")

    def __str__(self): return "<TrackedEdge: '{0}'>".format(self.id)
    def __name__(self): return "TrackedEdge"

    def __dict__(self) -> dict:
        """
        Returns the current state of edge data as a dictionary.
        :return dict: TrackedEdge data dictionary
        """
        edge_dict = {"linestring": self.linestring,
                     "length": self.length,
                     "to_node": self.to_node,
                     "from_node": self.from_node,
                     "n_lanes": self.n_lanes,
                     "step_vehicles": self.step_vehicles,
                     "init_time": self.init_time,
                     "curr_time": self.curr_time}
        
        return edge_dict

    def reset(self) -> None:
        """
        Resets edge data collection.
        """

        self.init_time = self.sim.curr_step
        self.curr_time = self.sim.curr_step

        self.step_vehicles = []

    def update(self) -> None:
        
        self.curr_time = self.sim.curr_step
        last_step_vehs = self.sim.get_last_step_geometry_vehicles(self.id, flatten=True)

        veh_data = []
        for veh_id in last_step_vehs:
            vals = self.sim.get_vehicle_vals(veh_id, ["speed", "position", "lane_idx"])
            pos = self._get_distance_on_road(vals["position"])
            if self.sim.units in ['IMPERIAL']: pos *= 0.0006213712
            veh_data.append((veh_id, pos, vals["speed"], vals["lane_idx"]))

        self.step_vehicles.append(veh_data)
            
    def _get_distance_on_road(self, veh_coors):
        line = LineString(self.linestring)
        p = Point(veh_coors)
        p2 = line.interpolate(line.project(p))
        x_val = line.line_locate_point(p2, False)
        x_pct = x_val/line.length
        return x_pct

def print_summary(sim_data, save_file=None, tab_width=58):
    """
    Prints a summary of a sim_data file or dictionary, listing
    simulation details, vehicle statistics, detectors, controllers,
    tracked edges/junctions and events.
    :param sim_data:  Simulation data dictionary or filepath
    :param save_file: '.txt' filename, if given will be used to save summary
    :param tab_width: Table width
    """
    caller = "{0}()".format(inspect.stack()[0][3])
    if save_file != None:
        if isinstance(save_file, str):
            if not save_file.endswith(".txt"): save_file += ".txt"
            old_stdout = sys.stdout
            sys.stdout = buffer = io.StringIO()
        else:
            desc = "{0}: Invalid save_file type (must be 'str', not '{1}').".format(caller, type(save_file).__name__)
            raise TypeError(desc)
    
    if isinstance(sim_data, str):
        if sim_data.endswith(".json"): r_class, r_mode = json, "r"
        elif sim_data.endswith(".pkl"): r_class, r_mode = pkl, "rb"
        else:
            desc = "{0}: sim_data file '{1}' is invalid (must be '.json' or '.pkl').".format(caller, sim_data)
            raise ValueError(desc)

        if os.path.exists(sim_data):
            with open(sim_data, r_mode) as fp:
                sim_data = r_class.load(fp)
        else:
            desc = "{0}: sim_data file '{1}' not found.".format(caller, sim_data)
            raise FileNotFoundError(desc)
    elif not isinstance(sim_data, dict):
        desc = "{0}: Invalid sim_data type (must be [str|dict], not '{1}').".format(caller, type(sim_data).__name__)
        raise TypeError(desc)
    elif len(sim_data.keys()) == 0 or "data" not in sim_data.keys():
        desc = "{0}: Invalid sim_data (no data found)."
        raise ValueError(desc)
    
    name = sim_data["scenario_name"]
    if math.floor((tab_width-len(name))/2) != math.ceil((tab_width-len(name))/2):
        tab_width += 1
    
    primary_delineator = " *"+"="*(tab_width+2)+"*"
    secondary_delineator = " *"+"-"*(tab_width+2)+"*"
    tertiary_delineator = " * "+"-"*tab_width+" *"
    
    print(primary_delineator)
    _table_print(sim_data["scenario_name"], tab_width)
    if "scenario_desc" in sim_data.keys():
        desc = sim_data["scenario_desc"]
        print(primary_delineator)
        if tab_width - len("Description: "+desc) > 0:
            _table_print("Description: "+desc, tab_width)
        else:
            _table_print("Description:", tab_width)
            desc_lines = _add_linebreaks(desc, tab_width)
            for line in desc_lines: _table_print(line, tab_width)
    print(primary_delineator)
    
    start_step, end_step = sim_data["start"], sim_data["end"]
    start_time, end_time = datetime.strptime(sim_data["sim_start"], datetime_format), datetime.strptime(sim_data["sim_end"], datetime_format)
    sim_duration, sim_duration_steps = end_time - start_time, end_step - start_step
    if start_time.date() == end_time.date():
        _table_print("Simulation Run: "+start_time.strftime(date_format), tab_width)
        _table_print("{0} - {1} ({2})".format(start_time.strftime(time_format), end_time.strftime(time_format), sim_duration), tab_width)
    else:
        _table_print("Simulation Run: ({0})".format(sim_duration), tab_width)
        _table_print([start_time.strftime(date_format), end_time.strftime(date_format)], tab_width, centre_cols=True)
        _table_print([start_time.strftime(time_format), end_time.strftime(time_format)], tab_width, centre_cols=True)
    
    print(secondary_delineator)
    _table_print(["Number of Steps:", "{0}".format(sim_duration_steps, start_step, end_step)], tab_width)
    _table_print(["Step Length:", sim_data["step_len"]], tab_width)
    _table_print(["Avg. Step Duration:", str(sim_duration.total_seconds() / sim_duration_steps)+"s"], tab_width)
    _table_print(["Units Type:", unit_desc[sim_data["units"]]], tab_width)
    _table_print(["Seed:", sim_data["seed"]], tab_width)
    
    print(primary_delineator)
    _table_print("Data", tab_width)
    print(primary_delineator)
    _table_print("Vehicle Data", tab_width)
    print(secondary_delineator)

    _table_print(["Avg. No. Vehicles:", round(sum(sim_data["data"]["vehicles"]["no_vehicles"])/len(sim_data["data"]["vehicles"]["no_vehicles"]), 2)], tab_width)
    _table_print(["Peak No. Vehicles:", int(max(sim_data["data"]["vehicles"]["no_vehicles"]))], tab_width)
    _table_print(["Avg. No. Waiting Vehicles:", round(sum(sim_data["data"]["vehicles"]["no_waiting"])/len(sim_data["data"]["vehicles"]["no_waiting"]), 2)], tab_width)
    _table_print(["Peak No. Waiting Vehicles:", int(max(sim_data["data"]["vehicles"]["no_waiting"]))], tab_width)
    _table_print(["Final No. Vehicles:", int(sim_data["data"]["vehicles"]["no_vehicles"][-1])], tab_width)
    _table_print(["Individual Data:", "Yes" if "all_vehicles" in sim_data["data"].keys() else "No"], tab_width)
    print(tertiary_delineator)
    _table_print(["Total TTS:", "{0}s".format(round(sum(sim_data["data"]["vehicles"]["tts"]), 2))], tab_width)
    _table_print(["Total Delay:", "{0}s".format(round(sum(sim_data["data"]["vehicles"]["delay"]), 2))], tab_width)

    print(secondary_delineator)
    _table_print("Trip Data", tab_width)
    print(secondary_delineator)
    n_inc, n_com = len(sim_data["data"]["trips"]["incomplete"]), len(sim_data["data"]["trips"]["completed"])
    _table_print(["Incomplete Trips:", "{0} ({1}%)".format(n_inc, round(100 * n_inc / (n_inc + n_com), 1))], tab_width)
    _table_print(["Completed Trips:", "{0} ({1}%)".format(n_com, round(100 * n_com / (n_inc + n_com), 1))], tab_width)

    print(secondary_delineator)
    _table_print("Detectors", tab_width)
    print(secondary_delineator)
    if "detectors" not in sim_data["data"].keys() or len(sim_data["data"]["detectors"]) == 0:
        _table_print("No detectors found.")
    else:
        ils, mees, unknown, labels = [], [], [], ["Induction Loop Detectors", "Multi-Entry-Exit Detectors", "Unknown Type"]
        for det_id, det_info in sim_data["data"]["detectors"].items():
            if det_info["type"] == "inductionloop": ils.append(det_id)
            elif det_info["type"] == "multientryexit": mees.append(det_id)
            else: unknown.append(det_id)
        
        add_spacing = False
        for ids, label in zip([ils, mees, unknown], labels):
            if len(ids) > 0:
                if add_spacing: _table_print(tab_width=tab_width)
                _table_print(label+": ({0})".format(len(ids)), tab_width)
                id_lines = _add_linebreaks(", ".join(ids), tab_width)
                for line in id_lines: _table_print(line, tab_width)
                add_spacing = True
 
    print(secondary_delineator)
    _table_print("Tracked Edges", tab_width)
    print(secondary_delineator)
    if "edges" not in sim_data["data"].keys() or len(sim_data["data"]["edges"]) == 0:
        _table_print("No tracked edges found.")
    else:
        id_lines = _add_linebreaks(", ".join(sim_data["data"]["edges"].keys()), tab_width)
        for line in id_lines: _table_print(line, tab_width)
        
    print(secondary_delineator)
    _table_print("Tracked Junctions", tab_width)
    print(secondary_delineator)
    if "junctions" not in sim_data["data"].keys() or len(sim_data["data"]["junctions"]) == 0:
        _table_print("No tracked junctions found.")
    else:
        for junc_id, junc_info in sim_data["data"]["junctions"].items():
            j_arr = []
            if "tl" in junc_info.keys(): j_arr.append("Signalised")
            if "meter" in junc_info.keys(): j_arr.append("Metered")
            if len(j_arr) == 0: j_arr.append("Uncontrolled")
            _table_print("{0} ({1})".format(junc_id, ", ".join(j_arr)), tab_width)

    if "controllers" in sim_data["data"].keys():
        print(secondary_delineator)
        _table_print("Controllers", tab_width)
        print(secondary_delineator)

        rgs, vsls, unknown, labels = [], [], [], ["Route Guidance", "Variable Speed Limits", "Unknown Type"]
        for cont_id, cont_info in sim_data["data"]["controllers"].items():
            if cont_info["type"] == "RG": rgs.append(cont_id)
            elif cont_info["type"] == "VSL": vsls.append(cont_id)
            else: unknown.append(cont_id)
        
        add_spacing = False
        for ids, label in zip([rgs, vsls, unknown], labels):
            if len(ids) > 0:
                if add_spacing: _table_print(tab_width=tab_width)
                _table_print(label+": ({0})".format(len(ids)), tab_width)
                id_lines = _add_linebreaks(", ".join(ids), tab_width)
                for line in id_lines: _table_print(line, tab_width)
                add_spacing = True
        

    if "events" in sim_data["data"].keys():
        event_statuses = []
        for s in ["scheduled", "active", "completed"]:
            if s in sim_data["data"]["events"].keys() and len(sim_data["data"]["events"][s]) > 0:
                event_statuses.append(s)

        if len(event_statuses) >= 0:
            print(secondary_delineator)
            _table_print("Event IDs & Statuses", tab_width)
            print(secondary_delineator)

            for event_status in event_statuses:
                event_ids = [event["id"] for event in sim_data["data"]["events"][event_status]]
                event_str = "{0}: {1}".format(event_status.title(), ", ".join(event_ids))
                event_lines = _add_linebreaks(event_str, tab_width)
                for line in event_lines: _table_print(line, tab_width)

    print(secondary_delineator)

    if save_file != None:
        sys.stdout = old_stdout
        summary = buffer.getvalue()
        with open(save_file, "w") as fp:
            fp.write(summary)
        print(summary)

def _table_print(strings=None, tab_width=58, side=" | ", padding=" ", centre_cols=False):
    
    if strings == None: strings = ""
    print_str = None
    if isinstance(strings, str):
        print_str = side+_centre_str(strings, tab_width)+side
    elif isinstance(strings, (list, tuple)):
        if centre_cols:
            col_spacing = padding*math.floor((tab_width - sum([len(str(string)) for string in strings])) / (len(strings) + 1))
            print_str = col_spacing+col_spacing.join([str(string) for string in strings])+col_spacing
            print_str = side+_centre_str(print_str, tab_width)+side
        else:
            col_spacing = padding*math.floor((tab_width - sum([len(str(string)) for string in strings])) / (len(strings) - 1))
            print_str = side+col_spacing.join([str(string) for string in strings])+side
    else:
        desc = "_table_print(): Invalid type (must be [str|list|tuple], not '{0}').".format(type(strings).__name__)
        raise TypeError(desc)
    
    if print_str != None:
        print(print_str)
    else: exit()

def _centre_str(string, width, padding=" "):
    if len(string) > width: return string
    else: return padding*math.floor((width-len(string))/2)+string+padding*math.ceil((width-len(string))/2)

def _add_linebreaks(string, width):
    lines = []
    while string != "":
        if " " not in string or len(string) < width:
            lines.append(string)
            break
        elif " " in string and len(string) > width:
            max_len_str = string[:width]
            line_break_index = max_len_str.rfind(" ")
            lines.append(max_len_str[:line_break_index])
            string = string[line_break_index+1:]
    return lines
