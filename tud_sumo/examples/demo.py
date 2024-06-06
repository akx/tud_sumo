
from random import randint, seed
import sys
from tqdm import tqdm

seed(1)

sys.path.insert(0, '..')
from simulation import *
from plot import Plotter

if __name__ == "__main__":

    # Initialise the simulation object.
    my_sim = Simulation(scenario_name="A20_ITCS", scenario_desc="Example traffic controllers, with a ramp meter, VSL controller and route guidance.")

    # Start the simulation, defining the sumo config files.
    my_sim.start("example_scenario/a20.sumocfg", get_individual_vehicle_data=False, gui="-gui" in sys.argv,
                 seed="random" if "-seed" not in sys.argv[:-1] else sys.argv[sys.argv.index("-seed")+1],
                 units=1) # Units can either be metric (km,kmph)/imperial (mi,mph)/UK (km,mph). All data collected is in these units.

    # Add a tracked junction to the intersection with ID "utsc", which will track signal phases/times.
    my_sim.add_tracked_junctions({"utsc": {"flow_params": {"inflow_detectors": ["utsc_n_in_1", "utsc_n_in_2", "utsc_w_in", "utsc_e_in"],
                                                           "outflow_detectors": ["utsc_w_out", "utsc_e_out"],
                                                           "flow_vtypes": ["cars", "lorries", "motorcycles", "vans"]}}})

    # Set traffic signal phases. The junc_phases dict can be used for multiple junctions.
    my_sim.set_phases({"utsc": {"phases": ["GGrr", "yyrr", "rrGG", "rryy"], "times": [27, 3, 17, 3]}})

    # Add a ramp meter to the junction with ID "crooswijk_meter". The junc_params dict can be used to
    # define meter specifc parameters (min/max rate, spillback tracking or queue detectors) and flow specific
    # parameters (inflow/outflow detectors used to calculate in/out flow).
    my_sim.add_tracked_junctions({"crooswijk_meter": {'meter_params': {'min_rate': 200, 'max_rate': 2000, 'queue_detector': "cw_ramp_queue"},
                                                    'flow_params': {'inflow_detectors': ["cw_ramp_inflow", "cw_rm_upstream"], 'outflow_detectors': ["cw_rm_downstream"]}},
                                  "a13_meter": {'meter_params': {'min_rate': 200, 'max_rate': 2000, 'queue_detector': "a13_ramp_queue"},
                                                'flow_params': {'inflow_detectors': ["a13_ramp_inflow", "a13_rm_upstream"], 'outflow_detectors': ["a13_rm_downstream"]}}})
    
    # Add Route Guidance (RG) & Variable Speed Limit (VSL) controllers. RG controllers need a detector or
    # edge that will act as the redirection point and a target edge/route ID to redirect drivers to. It is
    # also possible to define a diversion percent to randomly divert a certain percent of drivers, and a
    # highlight colour for the SUMO gui, which will highlight affected drivers. VSL controllers only need
    # to have a list of lanes/edges where they will operate.
    my_sim.add_controllers({"rerouter": {"type": "RG", "detector_ids": ["rerouter_2"], "new_destination": "urban_out_w", "diversion_pct": 0.25, "highlight": "00FF00"},
                            "vsl": {"type": "VSL", "geometry_ids": ["126729982", "126730069", "126730059"]}})

    # Add tracked edges. This will track some basic information, such as average speed etc, but can also
    # be used to create space-time diagrams as individual vehicle speeds and positions are tracked.
    my_sim.add_tracked_edges(["126730026", "1191885773", "1191885771", "126730171", "1191885772", "948542172", "70944365", "308977078", "1192621075"])

    # Add scheduled events from a JSON file (can be dictionary). Use the format as in example_incident.json
    my_sim.add_events("example_scenario/example_incident.json")

    n, sim_dur = 50, 500
    pbar = tqdm(desc="Running sim (step 0, 0 vehs)", total=sim_dur)
    while my_sim.curr_step < sim_dur:

        # Set ramp metering rate.
        my_sim.set_tl_metering_rate("crooswijk_meter", randint(1200, 2000))
        my_sim.set_tl_metering_rate("a13_meter", randint(1200, 2000))
        
        # Step through n steps.
        my_sim.step_through(n, pbar=pbar)

        # Add a new vehicle
        if my_sim.curr_step % n == 0:
            my_sim.add_vehicle("lorry_"+str(randint(0, 100)), "lorries", ("urban_in_e", "urban_out_w"), origin_lane="first")
            my_sim.add_vehicle("car_"+str(randint(0, 100)), "cars", ("urban_in_w", "urban_out_e"))

        if my_sim.curr_step == 250:
            # Activate controllers & update UTSC phases.
            my_sim.controllers["rerouter"].activate()
            my_sim.controllers["vsl"].set_limit(60)

            my_sim.set_phases({"utsc": {"phases": ["GGrr", "yyrr", "rrGG", "rryy"], "times": [37, 3, 7, 3]}}, overwrite=False)

        if my_sim.curr_step == 400:
            my_sim.controllers["vsl"].set_limit(40)

        # Deactivate controllers.
        if my_sim.curr_step == 450:
            my_sim.controllers["rerouter"].deactivate()
            my_sim.controllers["vsl"].deactivate()

    # End the simulation.
    my_sim.end()

    # Save the simulation data & print a summary, which is also saved.
    my_sim.save_data("example_data.json")
    my_sim.print_summary(save_file="example_summary.txt")
    