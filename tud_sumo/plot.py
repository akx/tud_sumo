import json, math, os.path, numpy as np, pickle as pkl
from copy import deepcopy
from random import random, seed, choice

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.colors import is_color_like as is_mpl_colour
from mpl_toolkits.axes_grid1 import make_axes_locatable

from .simulation import Simulation
from .utils import *

default_labels = {"no_vehicles": "No. of Vehicles", "no_waiting": "No. of Waiting Vehicles", "tts": "Total Time Spent (s)", "delay": "Delay (s)", "throughput": "Throughput (veh/hr)",
                  "vehicle_counts": "No. of Vehicles", "occupancies": "Occupancy (%)", "densities": "Density unit", "metres": "Distance (m)", "kilometres": "Distance (km)",
                  "yards": "Distance (yd)", "feet": "Distance (ft)", "miles": "Distance (mi)", "m/s": "Speed (m/s)", "kmph": "Speed (kmph)", "mph": "Speed (mph)", "steps": "Time (Simulation Steps)",
                  "seconds": "Time (s)", "minutes": "Time (m)", "hours": "Time (hr)"}

default_titles = {"no_vehicles": "Number of Vehicles", "no_waiting": "Number of Waiting Vehicles", "tts": "Total Time Spent", "delay": "Delay",
                  "vehicle_counts": "Number of Vehicles", "occupancies": "Vehicle Occupancies", "densities": "Vehicle Density",
                  "speeds": "Average Speed", "limits": "Speed Limit", "throughput": "Throughput"}

# TU Delft colours as defined here: https://www.tudelft.nl/huisstijl/bouwstenen/kleur
tud_colours = {"cyaan": "#00A6D6", "donkerblauw": "#0C2340", "turkoois": "#00B8C8", "blauw": "#0076C2", "paars": "#6F1D77", "roze": "#EF60A3",
               "framboos": "#A50034", "rood": "#E03C31", "oranje": "#EC6842", "geel": "#FFB81C", "lichtgroen": "#6CC24A", "donkergroen": "#009B77"}

class Plotter:
    def __init__(self, simulation: Simulation|str, sim_label: str|None=None, time_unit: str="seconds", save_fig_loc: str="", save_fig_dpi: int=600, overwrite_figs: bool=True) -> None:
        """
        :param simulation:     Either simulation object, sim_data dict or sim_data filepath
        :param sim_label:      Simulation or scenario label added to the beginning of all plot titles
        :param time_unit:      Plotting time unit used for all plots (must be ['steps'|'seconds'|'minutes'|'hours'])
        :param save_fig_loc:   Figure filepath when saving (defaults to current file)
        :param save_fig_dpi:   Figure dpi when saving (defaults to 600dpi)
        :param overwrite_figs: Bool denoting whether to allow overwriting of saved figures with the same name
        """

        self.simulation = None
        if isinstance(simulation, Simulation):
            self.simulation = simulation
            self.sim_data = simulation.__dict__()
            self.units = simulation.units.name
            scenario_name = simulation.scenario_name

        elif isinstance(simulation, str):

            if simulation.endswith(".json"): r_class, r_mode = json, "r"
            elif simulation.endswith(".pkl"): r_class, r_mode = pkl, "rb"
            else:
                desc = "Invalid simulation file '{0}' (must be '.json' or '.pkl' file).".format(simulation)
                raise_error(ValueError, desc)

            if os.path.exists(simulation):
                with open(simulation, r_mode) as fp:
                    self.sim_data = r_class.load(fp)
                    self.units = self.sim_data["units"]
                    scenario_name = self.sim_data["scenario_name"]
            else:
                desc = "Simulation file '{0}' not found.".format(simulation)
                raise_error(FileNotFoundError, desc)

        elif isinstance(simulation, dict): self.sim_data, self.units, scenario_name = simulation, simulation["units"], simulation["scenario_name"]

        else:
            desc = "Invalid simulation type (must be Simulation|str|dict, not '{0}').".format(type(simulation).__name__)
            raise_error(TypeError, desc)

        if isinstance(sim_label, str) and sim_label.upper() == "SCENARIO": self.sim_label = scenario_name + ": "
        elif sim_label != None: self.sim_label = sim_label + ": "
        else: self.sim_label = ""
        
        avg_speed, speed, limit = "Avg. Speed ", "Vehicle Speed ", "Speed Limit "

        if self.units in ["IMPERIAL", "UK"]:
            avg_speed += "(mph)"
            speed += "(mph)"
            limit += "(mph)"
        elif self.units in ["METRIC"]:
            avg_speed += "(km/h)"
            speed += "(km/h)"
            limit += "(km/h)"
        else:
            desc = "Invalid simulation units '{0}' (must be 'METRIC'|'IMPERIAL'|'UK').".format(self.units.upper())
            raise_error(ValueError, desc)

        if time_unit.lower() in ["steps", "seconds", "minutes", "hours"]:
            self.time_unit = time_unit.lower()
        else:
            desc = "Invalid simulation time unit '{0}' (must be 'steps'|'seconds'|'hours').".format(time_unit)
            raise_error(ValueError, desc)
        
        default_labels["sim_time"] = "Simulation Time ({0})".format(self.time_unit)
        default_labels["speeds"] = avg_speed
        default_labels["speed"] = speed
        default_labels["limits"] = limit

        self.save_fig_loc, self.overwrite_figs = save_fig_loc, overwrite_figs
        if self.save_fig_loc != "":
            if not self.save_fig_loc.endswith('/'): self.save_fig_loc += "/"
            if not os.path.exists(self.save_fig_loc):
                desc = "File path '{0}' does not exist.".format(self.save_fig_loc)
                raise_error(FileNotFoundError, desc)
            
        self.save_fig_dpi = save_fig_dpi

        self.CYAAN = tud_colours["cyaan"]
        self.DONKERBLAUW = tud_colours["donkerblauw"]
        self.TURKOOIS = tud_colours["turkoois"]
        self.BLAUW = tud_colours["blauw"]
        self.PAARS = tud_colours["paars"]
        self.ROZE = tud_colours["roze"]
        self.FRAMBOOS = tud_colours["framboos"]
        self.ROOD = tud_colours["rood"]
        self.ORANJE = tud_colours["oranje"]
        self.GEEL = tud_colours["geel"]
        self.LICHTGROEN = tud_colours["lichtgroen"]
        self.DONKERGROEN = tud_colours["donkergroen"]

        self.line_colours = [self.CYAAN, self.ORANJE, self.LICHTGROEN, self.TURKOOIS, self.BLAUW, self.PAARS,
                             self.DONKERBLAUW, self.ROZE, self.FRAMBOOS, self.ROOD, self.GEEL, self.DONKERGROEN]
        
        self._default_colour_idx = 0
        self._default_colour = self.line_colours[self._default_colour_idx]
        self._next_colour_idx = 0

    def __name__(self):
        return "Plotter"
    
    def _display_figure(self, filename: str|None=None) -> None:
        """
        Display figure, either saving to file or showing on screen.
        :param filename: Save file name, if saving
        """

        if filename is None: plt.show()
        else:
            
            if not filename.endswith(".png") and not filename.endswith('.jpg'):
                filename += ".png"

            fp = self.save_fig_loc + filename
            if os.path.exists(fp) and not self.overwrite_figs:
                desc = "File '{0}' already exists.".format(fp)
                raise_error(FileExistsError, desc)
            
            plt.savefig(fp, dpi=self.save_fig_dpi)

        plt.close()
        
    def plot_junc_flows(self, junc_id: str, vehicle_types: list|tuple|None=None, plot_all: bool=True, time_range: list|tuple|None=None, show_events: bool=True, fig_title: str|None=None, save_fig: str|None=None) -> None:
        """
        Plot junction flow, either as inflow & outflow or number of vehicles at the intersection.
        :param junc_id:       Junction ID
        :param vehicle_types: Vehicle type ID or list of IDs
        :param plot_all:      If true, plot total values as well as vehicle type data
        :param time_range:    Plotting time range (in plotter class units)
        :param show_events:   Bool denoting whether to plot when events occur
        :param fig_title:     If given, will overwrite default title
        :param save_fig:      Output image filename, will show image if not given
        """

        if self.simulation != None:

            self.sim_data = self.simulation.__dict__()
            self.units = self.simulation.units.name

            if junc_id in self.simulation.tracked_junctions.keys(): tl = self.simulation.tracked_junctions[junc_id]
            else:
                desc = "Junction '{0}' not found in tracked junctions.".format(junc_id)
                raise_error(KeyError, desc)

            if tl.track_flow: junc_flows = tl.get_curr_data()["flows"]
            else:
                desc = "No traffic light at junction '{0}'.".format(junc_id)
                raise_error(ValueError, desc)

            step = self.simulation.step_length

        elif "junctions" in self.sim_data["data"].keys() and junc_id in self.sim_data["data"]["junctions"].keys():
            if "flows" in self.sim_data["data"]["junctions"][junc_id].keys():
                junc_flows = self.sim_data["data"]["junctions"][junc_id]["flows"]
                step = self.sim_data["step_len"]

            else:
                desc = "Junction '{0}' does not track flows (no detectors).".format(junc_id)
                raise_error(ValueError, desc)
        else:
            desc = "Junction '{0}' not found in tracked junctions.".format(junc_id)
            raise_error(KeyError, desc)

        if vehicle_types == None: vehicle_types = list(junc_flows["all_inflows"].keys())
        elif not isinstance(vehicle_types, (list, tuple)): vehicle_types = [vehicle_types]

        if "all" in vehicle_types and not plot_all: vehicle_types.remove("all")

        fig, ax = plt.subplots(1, 1)

        for vehicle_type_idx, vehicle_type in enumerate(vehicle_types):
            inflow_data, outflow_data = junc_flows["all_inflows"][vehicle_type], junc_flows["all_outflows"][vehicle_type]
            cumulative_inflow, cumulative_outflow = get_cumulative_arr(inflow_data), get_cumulative_arr(outflow_data)
            
            time_steps = get_time_steps(cumulative_inflow, self.time_unit, step)
            _, cumulative_inflow = limit_vals_by_range(time_steps, cumulative_inflow, time_range)
            time_steps, cumulative_outflow = limit_vals_by_range(time_steps, cumulative_outflow, time_range)

            linewidth = 1.5 if vehicle_type == "all" else 1
            inflow_line = plt.plot(time_steps, cumulative_inflow, color=self._get_colour("WHEEL", vehicle_type_idx==0), label=vehicle_type+' in', linewidth=linewidth)
            ax.plot(time_steps, cumulative_outflow, label=vehicle_type + ' out', linestyle='--', linewidth=linewidth, color=inflow_line[-1].get_color())

        fig_title = self.sim_label+"Vehicle Flows at Intersection '{0}'".format(junc_id) if fig_title == None else fig_title
        ax.set_title(fig_title, pad=20)
        ax.set_ylabel(default_labels["vehicle_counts"])
        ax.set_xlim([time_steps[0], time_steps[-1]])
        ax.set_ylim(bottom=0)
        ax.set_xlabel(default_labels["sim_time"])
        fig.tight_layout()
        ax.legend(title="Vehicle Types", fontsize="small", shadow=True)
        ax.grid(True, 'both', color='grey', linestyle='-', linewidth=0.5)

        if "events" in self.sim_data["data"].keys() and show_events:
            if "completed" in self.sim_data["data"]["events"]:
                self._plot_event(ax)
        
        fig.tight_layout()

        self._display_figure(save_fig)
    
    def plot_tl_colours(self, tl_id: str, plt_movements: list|tuple|None=None, plot_percent: bool=False, time_range: list|tuple|None=None, save_fig: str|None=None) -> None:
        """
        Plot traffic light sequence, as colours or green/red/yellow durations as a percent of time.
        :param tl_id:         Traffic light ID
        :param plt_movements: List of movements to plot by index (defaults to all)
        :param plot_percent:  Denotes whether to plot colours as percent of time
        :param time_range:    Plotting time range (in plotter class units)
        :param save_fig:      Output image filename, will show image if not given
        """

        plt_colour = {"G": self.DONKERGROEN, "Y": self.GEEL, "R": self.ROOD}

        if self.simulation != None:

            self.sim_data = self.simulation.__dict__()
            self.units = self.simulation.units.name

            if tl_id in self.simulation.tracked_junctions.keys(): tl = self.simulation.tracked_junctions[tl_id]
            else:
                desc = "Junction '{0}' not found in tracked junctions.".format(tl_id)
                raise_error(KeyError, desc)

            if tl.has_tl: tl_durs = deepcopy(tl.durations)
            else:
                desc = "No traffic light at junction '{0}'.".format(tl_id)
                raise_error(ValueError, desc)

            m_len = tl.m_len
            init_time = tl.init_time

        elif "junctions" in self.sim_data["data"].keys() and tl_id in self.sim_data["data"]["junctions"].keys():
            if "tl" in self.sim_data["data"]["junctions"][tl_id].keys():
                tl_durs = deepcopy(self.sim_data["data"]["junctions"][tl_id]["tl"]["m_phases"])
                m_len, init_time = self.sim_data["data"]["junctions"][tl_id]["tl"]["m_len"], self.sim_data["data"]["junctions"][tl_id]["init_time"]

            else:
                desc = "No traffic light at junction '{0}'.".format(tl_id)
                raise_error(ValueError, desc)
        else:
            desc = "Junction '{0}' not found in tracked junctions.".format(tl_id)
            raise_error(KeyError, desc)

        if plt_movements != None:
            m_mask = plt_movements
            m_mask.sort()
            for idx in m_mask:
                if idx >= m_len or idx < 0:
                    desc = "Invalid movement index '{0}' (must be 0 <= idx <= {1})".format(idx, m_len - 1)
                    raise_error(ValueError, desc)
            for i in reversed(range(m_len)):
                if i not in m_mask: tl_durs.pop(i)

            m_len = len(m_mask)

        xlim = convert_units([self.sim_data["start"] * self.sim_data["step_len"], self.sim_data["end"] * self.sim_data["step_len"]], "steps", self.time_unit, self.sim_data["step_len"])
        if isinstance(time_range, (list, tuple)) and time_range != None:
            if len(time_range) != 2:
                desc = "Invalid time range (must have length 2, not {0}).".format(len(time_range))
                raise_error(ValueError, desc)
            elif time_range[0] >= time_range[1]:
                desc = "Invalid time range (start_time ({0}) >= end_time ({1})).".format(start_time, end_time)
                raise_error(ValueError, desc)
            else:
                clipped_tl_durs = []
                start_time, end_time = time_range[0], time_range[1]
                xlim = time_range
                for m in tl_durs:
                    phase_times, phase_colours = [convert_units(c_dur, "steps", self.time_unit, self.sim_data["step_len"]) for (_, c_dur) in m], [colour for (colour, _) in m]
                    cum_phase_times = list(np.cumsum(phase_times))
                    if start_time < 0 or end_time > cum_phase_times[-1]:
                        desc = "Invalid time range (values [{0}-{1}] must be in range [0-{2}]).".format(start_time, end_time, cum_phase_times[-1])
                        raise_error(ValueError, desc)

                    times_in_range = [time >= start_time and time <= end_time for time in cum_phase_times]
                    
                    if True in times_in_range:
                        start_phase, end_phase = np.where(times_in_range)[0][0], np.where(times_in_range)[0][-1]
                        new_m_dur = [[phase_colours[i], phase_times[i]] for i in range(start_phase, end_phase + 1)]
                        
                        new_m_dur[0][1] = new_m_dur[0][1] + cum_phase_times[start_phase-1] - start_time if start_phase >= 1 else new_m_dur[0][1] - start_time
                        
                        # Add end buffer for last phase
                        if end_phase < len(cum_phase_times) - 1 and end_time - cum_phase_times[end_phase] > 0:
                            new_m_dur.append([phase_colours[end_phase + 1], end_time - cum_phase_times[end_phase]])
                        
                    else:
                        # If start_time and end_time both in same phase
                        times_after_start = [time >= start_time for time in cum_phase_times]
                        start_phase = np.where(times_after_start)[0][0]
                        new_m_dur = [[phase_colours[start_phase], end_time - start_time]]

                    clipped_tl_durs.append(new_m_dur)
                
                tl_durs = clipped_tl_durs

        fig, ax = plt.subplots(1, 1)

        if plot_percent:
            percent_tl_durs = [[] for _ in range(m_len)]
            for idx, m_durs in enumerate(tl_durs):
                total_len = sum([x[1] for x in m_durs])
                percent_tl_durs[idx].append(['G', sum([x[1] for x in m_durs if x[0] == 'G']) / total_len * 100])
                percent_tl_durs[idx].append(['Y', sum([x[1] for x in m_durs if x[0] == 'Y']) / total_len * 100])
                percent_tl_durs[idx].append(['R', sum([x[1] for x in m_durs if x[0] == 'R']) / total_len * 100])

            tl_durs = percent_tl_durs
            ax.set_xlabel("Movements")
            ax.set_ylabel("Colour Duration (%)")
            ax.set_ylim((0, 100))
        else:
            ax.set_xlabel(default_labels["sim_time"])
            ax.set_ylabel("Movement")
            ax.set_xlim(xlim)

        if plt_movements == None: ms = list([str(i) for i in range(1, m_len + 1)])
        else: ms = list([str(i) for i in m_mask])

        curr_colour = 'G'
        all_plotted = False

        if time_range != None: offset_value = time_range[0]
        else: offset_value = init_time
        offset = [offset_value for _ in range(m_len)]

        while not all_plotted:

            curr_bar = [0 for _ in range(m_len)]
            for idx, m_durs in enumerate(tl_durs):
                if len(m_durs) == 0: continue
                
                if m_durs[0][0] == curr_colour:
                    curr_bar[idx] = convert_units(m_durs[0][1], "steps", self.time_unit, self.sim_data["step_len"])
                    tl_durs[idx].pop(0)
            
            all_plotted = True
            for m_durs in tl_durs:
                if len(m_durs) != 0: all_plotted = False
            
            if plot_percent: ax.bar(ms, curr_bar, bottom=offset, color=plt_colour[curr_colour])
            else: ax.barh(ms, curr_bar, left=offset, color=plt_colour[curr_colour])

            for m in range(m_len): offset[m] = offset[m] + curr_bar[m]

            if curr_colour == 'G': curr_colour = 'Y'
            elif curr_colour == 'Y': curr_colour = 'R'
            elif curr_colour == 'R': curr_colour = 'G'

        ax.set_title(self.sim_label+"Light Phase Durations", pad=20)
        fig.tight_layout()
        self._display_figure(save_fig)

    def plot_rm_rate(self, rm_id: str, ax=None, yax_labels: bool=True, xax_labels: bool=True, show_legend: bool=True, time_range: list|tuple|None=None, show_events: bool=True, fig_title: str|None=None, save_fig: str|None=None) -> None:
        """
        Plot ramp metering rate.
        :param rm_id:       Ramp meter junction ID
        :param ax:          Matplotlib axis, used when creating subplots
        :param yax_labels:  Bool denoting whether to include y-axis labels (for subplots)
        :param xax_labels:  Bool denoting whether to include x-axis labels (for subplots)
        :param show_legend: Bool denoting whether to show figure legend
        :param time_range:  Plotting time range (in plotter class units)
        :param show_events: Bool denoting whether to plot events on all axes
        :param fig_title:   If given, will overwrite default title
        :param save_fig:    Output image filename, will show image if not givenr
        """

        if self.simulation != None:

            self.sim_data = self.simulation.__dict__()
            self.units = self.simulation.units.name

            if rm_id in self.simulation.tracked_junctions.keys(): tl = self.simulation.tracked_junctions[rm_id]
            else:
                desc = "Junction '{0}' not found in tracked junctions.".format(rm_id)
                raise_error(KeyError, desc)

            if tl.is_meter:
                rates = tl.metering_rates
                times = tl.rate_times
                min_r, max_r = tl.min_rate, tl.max_rate
            else:
                desc = "Junction '{0}' is not tracked as a meter.".format(rm_id)
                raise_error(ValueError, desc)

        elif "junctions" in self.sim_data["data"].keys() and rm_id in self.sim_data["data"]["junctions"].keys():
            if "meter" in self.sim_data["data"]["junctions"][rm_id].keys():
                rates = self.sim_data["data"]["junctions"][rm_id]["meter"]["metering_rates"]
                times = self.sim_data["data"]["junctions"][rm_id]["meter"]["rate_times"]
                min_r, max_r = self.sim_data["data"]["junctions"][rm_id]["meter"]["min_rate"], self.sim_data["data"]["junctions"][rm_id]["meter"]["max_rate"]

            else:
                desc = "Junction '{0}' is not tracked as a meter.".format(rm_id)
                raise_error(ValueError, desc)
        else:
            desc = "Junction '{0}' not found in tracked junctions.".format(rm_id)
            raise_error(KeyError, desc)

        start, end, step = self.sim_data["start"], self.sim_data["end"], self.sim_data["step_len"]

        start = convert_units(start, "steps", self.time_unit, step)
        end = convert_units(end, "steps", self.time_unit, step)
        times = convert_units(times, "steps", self.time_unit, step)

        is_subplot = ax != None
        if not is_subplot: fig, ax = plt.subplots(1, 1)
        
        colour = self.CYAAN
        prev, label = None, "Metering Rate"
        for idx, val in enumerate(rates):
            if prev != None:
                
                line_start, line_end = times[int(idx - 1)], times[idx]
                if time_range != None:
                    if line_start >= time_range[1] or line_end <= time_range[0]: continue
                    else: line_start, line_end = max(line_start, time_range[0]), min(line_end, time_range[1])

                ax.plot([line_start, line_end], [prev, prev], label=label, color=colour, linewidth=1.5, zorder=3)
                
                # Vertical Line
                if time_range == None or (times[idx] > time_range[0] and times[idx] < time_range[1]):
                    ax.plot([times[idx], times[idx]], [prev, val], color=colour, linewidth=1.5, zorder=3)
                label = None

            prev = val

        if label != None: ax.plot([-1, -2], [-1, -2], label=label, color=colour, linewidth=1.5, zorder=3)

        last_line = [times[-1], end]
        if time_range != None:
            if last_line[0] >= time_range[1] or last_line[1] <= time_range[0]: last_line = None
            else: last_line[0], last_line[1] = max(last_line[0], time_range[0]), min(last_line[1], time_range[1])
        
        if last_line != None: ax.plot(last_line, [rates[-1], rates[-1]], color=colour, linewidth=1.5, zorder=3)

        xlim = [start, end]
        if time_range != None:
            xlim[0], xlim[1] = max(xlim[0], time_range[0]), min(xlim[1], time_range[1])
        ax.set_xlim(xlim)
        ax.set_ylim([0, get_axis_lim(max_r)])
        ax.axhline(max_r, label="Min/Max Rate", color=self.ROOD, linestyle="--", zorder=1)
        ax.axhline(min_r, color=self.ROOD, linestyle="--", zorder=2)
        ax.grid(True, 'both', color='grey', linestyle='-', linewidth=0.5)
        if yax_labels: ax.set_ylabel("Metering Rate (veh/hr)")
        if xax_labels: ax.set_xlabel(default_labels["sim_time"])
        fig_title = "{0}'{1}' Metering Rate".format(self.sim_label, rm_id) if not isinstance(fig_title, str) else fig_title
        if fig_title != "": ax.set_title(fig_title, pad=20)

        if show_legend:
            box = ax.get_position()
            if not is_subplot:
                ax.set_position([box.x0, box.y0 + box.height * 0.08,
                                box.width, box.height * 0.92])
                ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.13),
                        fancybox=True, ncol=2)
            else:
                ax.set_position([box.x0, box.y0 + box.height * 0.02,
                                box.width, box.height * 0.80])
                ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.2),
                        fancybox=True, ncol=2)
            
        if "events" in self.sim_data["data"].keys() and show_events:
            if "completed" in self.sim_data["data"]["events"]:
                self._plot_event(ax)

        if not is_subplot:
            self._display_figure(save_fig)

    def plot_rm_rate_detector_data(self, rm_ids: str|list|tuple, all_detector_ids: list|tuple, data_keys: list|tuple, aggregate_data: int=10, data_titles: list|tuple|None=None, time_range: list|tuple|None=None, show_events: bool=True, fig_title: str|None=None, save_fig: str|None=None) -> None:
        """
        Plot ramp metering rate next to detector data.
        :param rm_ids:         Ramp meter junction ID or list of IDs
        :param detector_ids:   List of detector IDs or nested list for multiple meters
        :param data_keys:      Plotting data keys ["speeds", "vehicle_counts", "occupancies"]
        :param aggregate_data: Averaging interval in steps (defaults to 10)
        :param data_titles:    List of axes titles, if given must have same length as data_keys
        :param time_range:     Plotting time range (in plotter class units)
        :param show_events:    Bool denoting whether to plot events on all axes
        :param fig_title:      If given, will overwrite default title
        :param save_fig:       Output image filename, will show image if not given
        """
        
        if self.simulation != None:
            self.sim_data = self.simulation.__dict__()
            self.units = self.simulation.units.name

        start, end, step = self.sim_data["start"], self.sim_data["end"], self.sim_data["step_len"]

        if not isinstance(rm_ids, (list, tuple)): rm_ids = [rm_ids]
        if not isinstance(all_detector_ids[0], (list, tuple)): all_detector_ids = [all_detector_ids]

        if len(rm_ids) != len(all_detector_ids):
            desc = "Number of rm_ids '{0}' and all_detector_ids groups '{1}' do not match.".format(len(rm_ids), len(all_detector_ids))
            raise_error(ValueError, desc)

        if isinstance(data_titles, (list, tuple)) and len(data_titles) != len(data_keys):
            desc = "Length of data_keys '{0}' and data_titles '{1}' do not match.".format(len(data_keys), len(data_titles))
            raise_error(ValueError, desc)

        fig_dimensions = 4 if len(rm_ids) == 1 else 3
        fig, all_axes = plt.subplots(len(rm_ids), 1+len(data_keys), figsize=((1+len(data_keys))*fig_dimensions, fig_dimensions*len(rm_ids)))
        
        if len(rm_ids) == 1: all_axes = [all_axes]
        else:
            new_axes = []
            new_row = []
            for col_idx in range(1+len(data_keys)):
                for rm_idx in range(len(rm_ids)):
                    new_row.append(all_axes[rm_idx][col_idx])
                new_axes.append(new_row)
                new_row = []
            all_axes = new_axes


        for rm_idx, (rm_id, detector_ids, axes) in enumerate(zip(rm_ids, all_detector_ids, all_axes)):
            self.plot_rm_rate(rm_id, axes[0],
                                    yax_labels=rm_idx==0, xax_labels=len(rm_ids)==1,
                                    show_legend=len(rm_ids)==1,
                                    time_range=time_range, show_events=show_events,
                                    fig_title="Metering Rate" if len(rm_ids) == 1 else rm_id)

            for idx, (data_key, ax) in enumerate(zip(data_keys, axes[1:])):

                all_detector_data = []
                for det_id in detector_ids:
                    if "detectors" in self.sim_data["data"].keys():
                        if det_id in self.sim_data["data"]["detectors"].keys():
                            if data_key in self.sim_data["data"]["detectors"][det_id].keys():
                                det_data = self.sim_data["data"]["detectors"][det_id][data_key]
                                all_detector_data.append(det_data)
                            else:
                                desc = "Unrecognised dataset key '{0}'.".format(data_key)
                                raise_error(KeyError, desc)
                        else:
                            desc = "Unrecognised detector ID '{0}'.".format(det_id)
                            raise_error(KeyError, desc)
                    else:
                        desc = "No detector data to plot."
                        raise_error(KeyError, desc)

                if len(set([len(data) for data in all_detector_data])) == 1:
                    n_steps = len(all_detector_data[0])
                else:
                    desc = "Mismatching detector data lengths."
                    raise_error(ValueError, desc)

                avg_data, steps, curr_step = [], [], start
                if time_range == None: time_range = [-math.inf, math.inf]
                
                while curr_step < end:
                    if curr_step < time_range[0]: 
                        curr_step += 1
                        continue
                    elif curr_step > time_range[1]: break
                    
                    step_data = [all_detector_data[det_idx][curr_step - start] for det_idx in range(len(detector_ids))]
                    step_data = [val for val in step_data if val != -1]

                    if len(step_data) > 0: avg_data.append(sum(step_data) / len(step_data))
                    else: avg_data.append(-1)
                    
                    steps.append(curr_step)
                    curr_step += 1

                if isinstance(aggregate_data, (int, float)):
                    avg_data, steps = get_aggregated_data(avg_data, steps, int(aggregate_data / step))
                
                steps = convert_units(steps, "steps", self.time_unit, step)

                ax.plot(steps, avg_data, color=self._get_colour("WHEEL", idx==0))

                xlim = [convert_units(start, "steps", self.time_unit, step), convert_units(end, "steps", self.time_unit, step)]
                if time_range != None:
                    xlim[0], xlim[1] = max(xlim[0], time_range[0]), min(xlim[1], time_range[1])

                ax.set_xlim(xlim)
                ax.set_ylim([0, get_axis_lim(avg_data)])
                ax.grid(True, 'both', color='grey', linestyle='-', linewidth=0.5)
                if rm_idx == 0: ax.set_ylabel(default_labels[data_key])
                if len(rm_ids) == 1 or data_key == data_keys[-1]: ax.set_xlabel(default_labels["sim_time"])
                
                if len(rm_ids) == 1:
                    if data_titles == None: ax.set_title(default_titles[data_key], pad=20)
                    else: ax.set_title(data_titles[idx], pad=20)

                if "events" in self.sim_data["data"].keys() and show_events:
                    if "completed" in self.sim_data["data"]["events"]:
                        self._plot_event(ax)

        if len(rm_ids) == 1:
            fig_title = "{0}'{1}' Data".format(self.sim_label, rm_id) if not isinstance(fig_title, str) else fig_title
        else: fig_title = "{0}Ramp Metering & Detector Data".format(self.sim_label, rm_id) if not isinstance(fig_title, str) else fig_title
        if fig_title != "": fig.suptitle(fig_title, fontweight='bold')
        fig.tight_layout()
        self._display_figure(save_fig)

    def plot_rm_queuing(self, rm_id: str, ax=None, yax_labels: bool|list|tuple=True, xax_labels: bool=True, plot_delay: bool=True, cumulative_delay: bool=False, time_range: list|tuple|None=None, show_events: bool=True, fig_title: str|None=None, save_fig: str|None=None) -> None:
        """
        Plot ramp metering rate.
        :param rm_id:            Ramp meter junction ID
        :param ax:               Matplotlib axis, used when creating subplots
        :param yax_labels:       Bool denoting whether to include y-axis labels (for subplots). Either single bool for both y-axis labels or list of two bools to set both y-axes (when plotting delay).
        :param xax_labels:       Bool denoting whether to include x-axis labels (for subplots)
        :param plot_delay:       Bool denoting whether to plot queue delay. This will be done on the same plot with a separate y-axis.
        :param cumulative_delay: Bool denoting whether to plot cumulative delay
        :param time_range:       Plotting time range (in plotter class units)
        :param show_events:      Bool denoting whether to plot events on all axes
        :param fig_title:        If given, will overwrite default title
        :param save_fig:         Output image filename, will show image if not given
        """

        if self.simulation != None:

            self.sim_data = self.simulation.__dict__()
            self.units = self.simulation.units.name

            if rm_id in self.simulation.tracked_junctions.keys(): tl = self.simulation.tracked_junctions[rm_id]
            else:
                desc = "Junction '{0}' not found in tracked junctions.".format(rm_id)
                raise_error(KeyError, desc)

            if tl.is_meter: 
                if tl.measure_queues:
                    queue_lengths = tl.queue_lengths
                    queue_delays = tl.queue_delays
                else:
                    desc = "Meter '{0}' does not track queue lengths (no queue detector).".format(rm_id)
                    raise_error(ValueError, desc)
            else:
                desc = "Junction '{0}' is not tracked as a meter.".format(rm_id)
                raise_error(ValueError, desc)

        elif "junctions" in self.sim_data["data"].keys() and rm_id in self.sim_data["data"]["junctions"].keys():
            if "meter" in self.sim_data["data"]["junctions"][rm_id].keys():
                if "queue_lengths" in self.sim_data["data"]["junctions"][rm_id]["meter"].keys():
                    queue_lengths = self.sim_data["data"]["junctions"][rm_id]["meter"]["queue_lengths"]
                    queue_delays = self.sim_data["data"]["junctions"][rm_id]["meter"]["queue_delays"]
                else:
                    desc = "Meter '{0}' has not tracked queue lengths (no queue detector).".format(rm_id)
                    raise_error(ValueError, desc)
            else:
                desc = "Junction '{0}' has not been tracked as a meter.".format(rm_id)
                raise_error(ValueError, desc)
        else:
            desc = "Junction '{0}' not found in tracked junctions.".format(rm_id)
            raise_error(KeyError, desc)

        start, end, step = self.sim_data["start"], self.sim_data["end"], self.sim_data["step_len"]

        is_subplot = ax != None
        if not is_subplot: fig, ax1 = plt.subplots(1, 1)
        else: ax1 = ax

        colour = self.CYAAN
        all_data_time_vals = convert_units([x for x in range(start, end)], "steps", self.time_unit, step)
        data_time_vals, queue_lengths = limit_vals_by_range(all_data_time_vals, queue_lengths, time_range)
        ax1.plot(data_time_vals, queue_lengths, linewidth=1, zorder=3, color=colour)
        if xax_labels: ax1.set_xlabel(default_labels["sim_time"])
        if (isinstance(yax_labels, bool) and yax_labels) or (isinstance(yax_labels, (list, tuple)) and len(yax_labels) == 2 and yax_labels[0]):
            ax1.set_ylabel("No. of On-ramp Vehicles")
        else:
            desc = "Invalid yax_label, must be bool or list of 2 bools denoting each axis."
            raise_error(TypeError, desc)

        if time_range == None: time_range = [-math.inf, math.inf]
        ax1.set_xlim([max(time_range[0], data_time_vals[0]), min(time_range[1], data_time_vals[-1])])
        ax1.set_ylim([0, get_axis_lim(queue_lengths)])

        ax1.grid(True, 'both', color='grey', linestyle='-', linewidth=0.5)
        if not is_subplot or fig_title != None:
            if not isinstance(fig_title, str):
                default_title = "{0}'{1}' Queue Lengths".format(self.sim_label, rm_id)
                if plot_delay and cumulative_delay: default_title += " & Cumulative Delay"
                elif plot_delay: default_title += " & Delay"
                fig_title = default_title
            ax1.set_title(fig_title, pad=20)

        if "events" in self.sim_data["data"].keys() and show_events:
            if "completed" in self.sim_data["data"]["events"]:
                self._plot_event(ax1)

        if plot_delay:
            ax1.tick_params(axis='y', labelcolor=colour)
            if (isinstance(yax_labels, bool) and yax_labels) or (isinstance(yax_labels, (list, tuple)) and len(yax_labels) == 2 and yax_labels[0]):
                ax1.set_ylabel("No. of On-ramp Vehicles", color=colour)
        
            colour = self.ROOD
            data_time_vals, queue_delays = limit_vals_by_range(all_data_time_vals, queue_delays, time_range)
            if cumulative_delay: queue_delays = get_cumulative_arr(queue_delays)
            ax2 = ax1.twinx()

            ax2.plot(data_time_vals, queue_delays, linewidth=1, zorder=3, color=colour)
            ax2.tick_params(axis='y', labelcolor=colour)
            if (isinstance(yax_labels, bool) and yax_labels) or (isinstance(yax_labels, (list, tuple)) and len(yax_labels) == 2 and yax_labels[1]):
                if cumulative_delay: ax2.set_ylabel("Cumulative Delay (s)", color=colour)
                else: ax2.set_ylabel("Delay (s)", color=colour)
            else: TypeError("Plotter.plot_rm_queuing(): Invalid yax_label, must be bool or list of 2 bools denoting each axis.")
            ax2.set_ylim([0, get_axis_lim(queue_delays)])

        if not is_subplot:
            fig.tight_layout()
            self._display_figure(save_fig)

    def plot_rm_rate_queuing(self, rm_ids: str|list|tuple, plot_queuing: bool=True, time_range: list|tuple|None=None, show_events: bool=True, fig_title: str|None=None, save_fig: str|None=None) -> None:
        """
        Plot meter queue length and delay.
        :param rm_ids:       Ramp meter junction ID or list of IDs
        :param plot_queuing: Bool denoting whether to plot queue lengths and delay (set False to only plot metering rate)
        :param time_range:   Plotting time range (in plotter class units)
        :param show_events:  Bool denoting whether to plot when events occur
        :param fig_title:    If given, will overwrite default title
        :param save_fig:     Output image filename, will show image if not given
        """

        if self.simulation != None:
            self.sim_data = self.simulation.__dict__()
            self.units = self.simulation.units.name

        if not isinstance(rm_ids, (list, tuple)): rm_ids = [rm_ids]
        
        fig_dimensions = 4
        if len(rm_ids) == 1:
            if plot_queuing:
                fig, (ax, ax2) = plt.subplots(1, 2, figsize=(fig_dimensions*2, fig_dimensions))
                self.plot_rm_queuing(rm_ids[0], ax2, True, True, True, False, time_range, show_events, fig_title="Queue Lengths & Delays")
            else: fig, ax = plt.subplots(1, 1)
            self.plot_rm_rate(rm_ids[0], ax,
                                    yax_labels=True, xax_labels=True,
                                    time_range=time_range,
                                    show_legend=False,
                                    show_events=show_events,
                                    fig_title="Metering Rate")
        
        else:
            nrows, ncols = 2 if plot_queuing else 1, len(rm_ids)
            fig, axes = plt.subplots(nrows, ncols, figsize=(ncols*fig_dimensions*1.2, nrows*fig_dimensions))

            for idx, rm_id in enumerate(rm_ids):
                ax = axes[0][idx] if plot_queuing else axes[idx]
                self.plot_rm_rate(rm_id, ax,
                                        yax_labels=idx==0,
                                        xax_labels=not plot_queuing,
                                        time_range=time_range,
                                        show_legend=False,
                                        show_events=show_events,
                                        fig_title=rm_id)
                
                if plot_queuing:
                    self.plot_rm_queuing(rm_id, axes[1][idx], (idx==0, idx==len(rm_ids)-1), True, True, False, time_range, show_events, "")

        if len(rm_ids) > 1:
            def_title = "Ramp Metering Rates"
            if plot_queuing: def_title += " & Queuing Data"
            fig_title = self.sim_label+def_title if not isinstance(fig_title, str) else fig_title
            if fig_title != "": fig.suptitle(fig_title, fontweight='bold')

        fig.tight_layout()
        self._display_figure(save_fig)

    def plot_vehicle_data(self, data_key: str, plot_cumulative: bool=False, time_range: list|tuple|None=None, show_events: bool=True, line_colour: str|None=None, fig_title: str|None=None, save_fig: str|None=None) -> None:
        """
        Plot network-wide vehicle data.
        :param data_key:        Data key to plot, either "no_vehicles", "no_waiting", "tts" or "delay"
        :param plot_cumulative: Bool denoting whether to plot cumulative values
        :param time_range:      Plotting time range (in plotter class units)
        :param show_events:     Bool denoting whether to plot when events occur
        :param line_colour:     Line colour for plot (defaults to TUD 'blauw')
        :param fig_title:       If given, will overwrite default title
        :param save_fig:        Output image filename, will show image if not given
        """

        if self.simulation != None:
            self.sim_data = self.simulation.__dict__()
            self.units = self.simulation.units.name

        if data_key not in ["no_vehicles", "no_waiting", "tts", "delay"]:
            desc = "Unrecognised data key '{0}' (must be ['no_vehicles'|'no_waiting'|'tts'|'delay']).".format(data_key)
            raise_error(KeyError, desc)

        fig, ax = plt.subplots(1, 1)
        start, step = self.sim_data["start"], self.sim_data["step_len"]

        y_vals = self.sim_data["data"]["vehicles"][data_key]
        if plot_cumulative: y_vals = get_cumulative_arr(y_vals)
        x_vals = get_time_steps(y_vals, self.time_unit, step, start)
        x_vals, y_vals = limit_vals_by_range(x_vals, y_vals, time_range)

        ax.plot(x_vals, y_vals, color=self._get_colour(line_colour))

        if fig_title == None:
            fig_title = default_titles[data_key]
            if plot_cumulative: fig_title = "Cumulative "+fig_title
            fig_title = self.sim_label + fig_title
        ax.set_title(fig_title, pad=20)

        ax.set_xlabel(default_labels["sim_time"])
        ax.set_ylabel(default_labels[data_key])
        ax.set_xlim([x_vals[0], x_vals[-1]])
        ax.set_ylim([0, get_axis_lim(y_vals)])
        ax.grid(True, 'both', color='grey', linestyle='-', linewidth=0.5)

        if "events" in self.sim_data["data"].keys() and show_events:
            if "completed" in self.sim_data["data"]["events"]:
                self._plot_event(ax)
        
        fig.tight_layout()

        self._display_figure(save_fig)

    def plot_detector_data(self, detector_id: str, data_key: str, plot_cumulative: bool=False, time_range: list|tuple|None=None, show_events: bool=True, line_colour: str|None=None, fig_title: str|None=None, save_fig: str|None=None) -> None:
        """
        Plot detector data.
        :param detector_id:     Detector ID
        :param data_key:        Data key to plot, either "speeds", "vehicle_counts" or "occupancies"
        :param plot_cumulative: Bool denoting whether to plot cumulative values
        :param time_range:      Plotting time range (in plotter class units)
        :param show_events:     Bool denoting whether to plot when events occur
        :param line_colour:     Line colour for plot (defaults to TUD 'blauw')
        :param fig_title:       If given, will overwrite default title
        :param save_fig:        Output image filename, will show image if not given
        """
        
        if self.simulation != None:
            self.sim_data = self.simulation.__dict__()
            self.units = self.simulation.units.name

        fig, ax = plt.subplots(1, 1)
        start, step = self.sim_data["start"], self.sim_data["step_len"]

        if data_key not in ["speeds", "vehicle_counts", "occupancies"]:
            desc = "Unrecognised data key '{0}' (must be [speeds|vehicle_counts|occupancies]).".format(data_key)
            raise_error(KeyError, desc)
        elif detector_id not in self.sim_data["data"]["detectors"].keys():
            desc = "Plotter.plot_detector_data(): Detector ID '{0}' not found.".format(detector_id)
            raise_error(KeyError, desc)
        elif data_key == "occupancy" and self.sim_data["data"]["detectors"][detector_id]["type"] == "multientryexit":
            desc = "Multi-Entry-Exit Detectors ('{0}') do not measure '{1}'.".format(detector_id, data_key)
            raise_error(ValueError, desc)
        
        y_vals = self.sim_data["data"]["detectors"][detector_id][data_key]
        if plot_cumulative: y_vals = get_cumulative_arr(y_vals)
        x_vals = get_time_steps(y_vals, self.time_unit, step, start)
        x_vals, y_vals = limit_vals_by_range(x_vals, y_vals, time_range)

        ax.plot(x_vals, y_vals, color=self._get_colour(line_colour))

        if fig_title == None:
            fig_title = "{0} (Detector '{1}')".format(default_titles[data_key], detector_id)
            if plot_cumulative: fig_title = "Cumulative "+fig_title
            fig_title = self.sim_label + fig_title
        ax.set_title(fig_title, pad=20)

        ax.set_xlabel(default_labels["sim_time"])
        ax.set_ylabel(default_labels[data_key])
        ax.set_xlim([x_vals[0], x_vals[-1]])
        if data_key == "occupancies": ax.set_ylim([0, 100])
        else: ax.set_ylim([0, get_axis_lim(y_vals)])
        ax.grid(True, 'both', color='grey', linestyle='-', linewidth=0.5)

        if "events" in self.sim_data["data"].keys() and show_events:
            if "completed" in self.sim_data["data"]["events"]:
                self._plot_event(ax)
        
        fig.tight_layout()

        self._display_figure(save_fig)

    def plot_od_demand(self, routing: str|list|tuple, plot_sim_dur=True, show_events: bool=True, line_colour: str|None=None, fig_title: str|None=None, save_fig: str|None=None) -> None:
        """
        Plots traffic demand added with TUD-SUMO.
        :param routing: Either route ID, 
        """

        if self.simulation != None:
            self.sim_data = self.simulation.__dict__()
            self.units = self.simulation.units.name

        fig, ax = plt.subplots(1, 1)
        demand_arrs = self.sim_data["data"]["demand"]["table"]
        
        step = self.sim_data["step_len"]
        if plot_sim_dur: start, end = self.sim_data["start"], self.sim_data["end"]
        else:
            start, end = 0, -math.inf
            for demand_arr in demand_arrs:
                end = max(end, demand_arr[1][1])

        start, end = int(start), int(end)
        demand_vals, added_val = [0] * (end - start), False
        time_steps = get_time_steps(demand_vals, self.time_unit, step, start)

        for demand_arr in demand_arrs:
            include = True
            arr_routing, vehs_per_step = demand_arr[0], demand_arr[2]
            arr_start, arr_end = int(demand_arr[1][0]), int(demand_arr[1][1])

            if isinstance(routing, str) and not isinstance(arr_routing, str):
                if routing != "all": continue

            elif isinstance(routing, str) and isinstance(arr_routing, str):
                if routing != arr_routing and routing != "all": continue
                
            elif isinstance(routing, (list, tuple)) and isinstance(arr_routing, (list, tuple)):
                if routing[0] != arr_routing[0] or routing[1] != arr_routing[1]: continue

            if arr_start > end or arr_end < start: continue
            if include:
                for idx in range(max(start, arr_start), min(end, arr_end)):
                    demand_vals[idx] += vehs_per_step
                    added_val = True

        if not added_val:
            desc = "Unknown routing '{0}' (no demand found).".format(routing)
            raise_error(KeyError, desc)

        #demand_vals = [val * 3600 for val in demand_vals]

        ax.plot(time_steps, demand_vals, color=self._get_colour(line_colour))
        ax.set_ylabel("Demand (vehicles/hour)")
        ax.set_xlabel(default_labels["sim_time"])
        ax.set_xlim([convert_units(start, "steps", self.time_unit, step), convert_units(end, "steps", self.time_unit, step)])
        ax.set_ylim([0, get_axis_lim(demand_vals)])
        ax.grid(True, 'both', color='grey', linestyle='-', linewidth=0.5)
        if fig_title == None:
            if routing == "all": fig_title = "Network-wide Demand"
            else:
                if isinstance(routing, str): fig_title = "Route '{0}' Demand".format(routing)
                else: fig_title = "OD Demand ('{0}')".format(' → '.join(routing))
        if self.sim_label != None: fig_title = self.sim_label + fig_title
        ax.set_title(fig_title, pad=20)

        if "events" in self.sim_data["data"].keys() and show_events:
            if "completed" in self.sim_data["data"]["events"]:
                self._plot_event(ax)
        
        fig.tight_layout()

        self._display_figure(save_fig)

    def plot_od_trip_times(self, od_pairs: list|tuple|None=None, vehicle_types: list|tuple|None=None, ascending_vals: bool=True, trip_time_unit: str="minutes", time_range: list|tuple|None=None, fig_title: str|None=None, save_fig: str|None=None) -> None:
        """
        Plots average trip times for Origin-Destination pairs.
        :param od_pairs:       (n x 2) list containing OD pairs. If not given, all OD pairs are plotted
        :param vehicle_types:  List of vehicle types for included trips (defaults to all)
        :param ascending_vals: If true, the largest values are plotted in the bottom-right, if false, top-left
        :param trip_time_unit: Time unit for displaying values, must be ['seconds'|'minutes'|'hours'], defaults to 'minutes'
        :param time_range:     Plotting time range (in plotter class units, separate to trip_time_unit parameter)
        :param fig_title:      If given, will overwrite default title
        :param save_fig:       Output image filename, will show image if not given
        """
        
        if trip_time_unit not in ["seconds", "minutes", "hours"]:
            desc = "Invalid time unit '{0}' (must be ['seconds'|'minutes'|'hours']).".format(trip_time_unit)
            raise_error(ValueError, desc)
        
        if self.simulation != None:
            self.sim_data = self.simulation.__dict__()
            self.units = self.simulation.units.name

        step = self.sim_data["step_len"]

        od_trip_times, add_new = {}, od_pairs == None
        all_origins, all_destinations = set([]), set([])
        if od_pairs != None:
            for pair in od_pairs:
                od_trip_times[pair[0]] = {pair[1]: []}
                all_origins.add(pair[0])
                all_destinations.add(pair[1])

        n_trips = 0
        com_trip_data = self.sim_data["data"]["trips"]["completed"]
        for trip in com_trip_data.values():
            origin, destination = trip["origin"], trip["destination"]
            veh_type = trip["vehicle_type"]

            if vehicle_types != None and veh_type not in veh_type: continue
            
            if origin not in od_trip_times.keys():
                if add_new:
                    od_trip_times[origin] = {}
                else: continue
            
            if destination not in od_trip_times[origin].keys():
                if add_new: od_trip_times[origin][destination] = []
                else: continue

            trip_time = convert_units(trip["arrival"] - trip["departure"], "steps", trip_time_unit, step)
            trip_departure, trip_arrival = convert_units([trip["departure"], trip["arrival"]], "steps", self.time_unit, step)

            if time_range != None and trip_departure < time_range[0] and trip_arrival > time_range[1]:
                continue

            od_trip_times[origin][destination].append(trip_time)
            all_origins.add(origin)
            all_destinations.add(destination)
            n_trips += 1
        
        if n_trips == 0:
            desc = "No trips found."
            raise_error(ValueError, desc)

        all_origins = list(all_origins)
        all_destinations = list(all_destinations)

        if add_new:
            avg_o_tts = []
            for o in all_origins:
                o_tts = [sum(d)/len(d) for d in od_trip_times[o].values()]
                avg_o_tts.append(sum(o_tts)/len(o_tts))
            
            all_origins = [x for _, x in sorted(zip(avg_o_tts, all_origins))]
            
            avg_d_tts = []
            for d in all_destinations:
                d_tts = []
                for o_data in od_trip_times.values():
                    if d in o_data.keys():
                        d_tts.append(sum(o_data[d])/len(o_data[d]))
                avg_d_tts.append(sum(d_tts)/len(d_tts))

            all_destinations = [x for _, x in sorted(zip(avg_d_tts, all_destinations))]

        att_matrix = np.empty((len(all_origins), len(all_destinations)))
        att_matrix[:] = np.nan
        
        if add_new and not ascending_vals:
            all_origins.reverse()
            all_destinations.reverse()

        for i, origin in enumerate(all_origins):
            for j, destination in enumerate(all_destinations):
                if destination in od_trip_times[origin].keys():
                    trip_times = od_trip_times[origin][destination]
                    att_matrix[i][j] = sum(trip_times) / len(trip_times)

        fig, ax = plt.subplots(1, 1, figsize=(6, 6))
        masked_array = np.ma.array(att_matrix, mask=np.isnan(att_matrix))
        cmap = matplotlib.cm.Reds
        cmap.set_bad('#f7f7f7')
        ax.matshow(masked_array, interpolation='nearest', cmap=cmap)

        ax.set_xticks(np.arange(len(all_destinations)), labels=all_destinations)
        ax.set_yticks(np.arange(len(all_origins)), labels=all_origins)
        ax.xaxis.set_ticks_position("bottom")
        ax.xaxis.set_label_position("top")
        ax.yaxis.set_label_position("right")

        for row in range(att_matrix.shape[0]):
            for col in range(att_matrix.shape[1]):
                if not np.isnan(att_matrix[row, col]):
                    ax.text(x=col, y=row, s=round(att_matrix[row, col], 2) if trip_time_unit != "seconds" else int(att_matrix[row, col]),
                            va='center', ha='center', color='white', path_effects=[pe.withStroke(linewidth=2, foreground="black")]) 

        plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")

        ax.set_xlabel("Destination ID")
        ax.set_ylabel("Origin ID")
        
        if fig_title == None:
            fig_title = self.sim_label + "Average Trip Times in {0}".format(time_desc[trip_time_unit])
        ax.set_title(fig_title, pad=30, fontweight='bold')

        fig.tight_layout()

        self._display_figure(save_fig)

    def plot_cumulative_curve(self, inflow_detectors: list|tuple|None=None, outflow_detectors: list|tuple|None=None, outflow_offset: int|float=0, time_range: list|tuple|None=None, show_events: bool=True, fig_title: str|None=None, save_fig: str|None=None) -> None:
        """
        Plot inflow and outflow cumulative curves, either system-wide or using inflow/outflow detectors (if given).
        :param inflow_detectors:  List of inflow detectors
        :param outflow_detectors: List of outflow detectors
        :param outflow_offset:    Offset for outflow values if not starting at t=0
        :param time_range:        Plotting time range (in plotter class units)
        :param show_events:       Bool denoting whether to plot when events occur
        :param fig_title:         If given, will overwrite default title
        :param save_fig:          Output image filename, will show image if not given
        """

        if self.simulation != None:
            self.sim_data = self.simulation.__dict__()
            self.units = self.simulation.units.name

        inflows, outflows = [], []
        start, end, step = self.sim_data["start"], self.sim_data["end"], self.sim_data["step_len"]

        if time_range == None: time_range = [-math.inf, math.inf]

        if inflow_detectors == None and outflow_detectors == None:

            inflows, outflows = [0] * (end - start+1), [0] * (end - start+1)

            trips = self.sim_data["data"]["trips"]
            for inc_trip in trips["incomplete"].values():
                inflows[inc_trip["departure"]] += 1
            
            for com_trip in trips["completed"].values():
                inflows[com_trip["departure"]] += 1
                outflows[com_trip["arrival"]] += 1

            x_vals = get_time_steps(inflows, self.time_unit, step, start)
            _, inflows = limit_vals_by_range(x_vals, inflows, time_range)
            x_vals, outflows = limit_vals_by_range(x_vals, outflows, time_range)

        else:
            if inflow_detectors == None or outflow_detectors == None:
                desc = "When using detectors, both inflow and outflow detectors are required."
                raise_error(TypeError, desc)
            
            if "detectors" not in self.sim_data["data"].keys():
                desc = "No detector data to plot."
                raise_error(KeyError, desc)
            
            detector_data = self.sim_data["data"]["detectors"]
            if not isinstance(inflow_detectors, (list, tuple)): inflow_detectors = [inflow_detectors]
            if not isinstance(outflow_detectors, (list, tuple)): outflow_detectors = [outflow_detectors]

            if len(set(inflow_detectors + outflow_detectors) - set(detector_data.keys())) != 0:
                desc = "Detectors ['{0}'] could not be found.".format("', '".join(list(set(inflow_detectors + outflow_detectors) - set(detector_data.keys()))))
                raise_error(KeyError, desc)

            prev_in_vehicles, prev_out_vehicles = set([]), set([])
            for step_no in range(self.sim_data["end"] - self.sim_data["start"]):

                curr_time = convert_units(step_no, "steps", self.time_unit, step)
                
                if curr_time >= time_range[0] and curr_time <= time_range[1]:

                    vehs_in, vehs_out = set([]), set([])

                    for detector_id in inflow_detectors: vehs_in = vehs_in | set(detector_data[detector_id]["vehicle_ids"][step_no])
                    for detector_id in outflow_detectors: vehs_out = vehs_out | set(detector_data[detector_id]["vehicle_ids"][step_no])

                    inflows.append(len(vehs_in - prev_in_vehicles))
                    outflows.append(len(vehs_out - prev_out_vehicles))

                    prev_in_vehicles = prev_in_vehicles | vehs_in
                    prev_out_vehicles = prev_out_vehicles | vehs_out

                elif curr_time > time_range[1]:
                    break

            start = max(time_range[0], start)
            x_vals = get_time_steps(inflows, self.time_unit, step, start)

        inflows = get_cumulative_arr(inflows)
        outflows = get_cumulative_arr(outflows)
        outflows = [val - outflow_offset for val in outflows]

        fig, ax = plt.subplots(1, 1)
        fig_title = "{0}Cumulative Arrival-Departure Curve".format(self.sim_label) if not isinstance(fig_title, str) else fig_title
        ax.set_title(fig_title, pad=20)
        
        ax.plot(x_vals, inflows, color=self.DONKERGROEN, label="Inflow", zorder=3)
        ax.plot(x_vals, outflows, color=self.ROOD, label="Outflow", zorder=4)
        ax.set_xlim([x_vals[0], x_vals[-1]])
        ax.set_ylim([0, get_axis_lim(inflows)])
        ax.grid(True, 'both', color='grey', linestyle='-', linewidth=0.5)
        ax.set_xlabel(default_labels["sim_time"])
        ax.set_ylabel("Cumulative No. of Vehicles")
        ax.legend(loc='lower right', shadow=True)

        if "events" in self.sim_data["data"].keys() and show_events:
            if "completed" in self.sim_data["data"]["events"]:
                self._plot_event(ax)

        fig.tight_layout()

        self._display_figure(save_fig)

    def plot_vsl_data(self, vsl_id: str, avg_geomtry_speeds: bool=False, time_range: list|tuple|None=None, show_events: bool=True, fig_title: str|None=None, save_fig: str|None=None) -> None:
        """
        Plot VSL settings and average vehicle speeds on affected edges.
        :param vsl_id:              VSL controller ID
        :param avg_geometry_speeds: Bool denoting whether to plot average edge speed, or individual edge data
        :param time_range:          Plotting time range (in plotter class units)
        :param show_events:         Bool denoting whether to plot when events occur
        :param fig_title:           If given, will overwrite default title
        :param save_fig:            Output image filename, will show image if not given
        """

        if self.simulation != None:
            self.sim_data = self.simulation.__dict__()
            self.units = self.simulation.units.name

        if "controllers" not in self.sim_data["data"].keys():
            desc = "No controllers used during simulation."
            raise_error(KeyError, desc)
        elif vsl_id not in self.sim_data["data"]["controllers"].keys():
            desc = "Controller ID '{0}' not found.".format(vsl_id)
            raise_error(KeyError, desc)
        
        vsl_data = self.sim_data["data"]["controllers"][vsl_id]
        if vsl_data["type"] != "VSL":
            desc = "Controller '{0}' is not a VSL controller.".format(vsl_id)
            raise_error(KeyError, desc)
        
        start, end, step = vsl_data["init_time"], vsl_data["curr_time"], self.sim_data["step_len"]
        
        colour = self.DONKERGROEN
        activation_times = vsl_data["activation_times"]

        if len(activation_times) == 0:
            desc = "VSL controller '{0}' has no data, likely was not activated.".format(vsl_id)
            raise_error(ValueError, desc)

        fig, ax = plt.subplots(1, 1)

        prev = None
        activated = False
        active_times, activated_time = [], None
        label = "Speed Limit"
        linewidth = 1.5 if avg_geomtry_speeds else 2
        for idx, (val, time) in enumerate(activation_times):
            if prev == None: prev = val
            else:
                if prev != -1 and val != -1:
                    ax.plot(convert_units([time, time], "steps", self.time_unit, step), [prev, val], color=colour, linewidth=linewidth, label=label, zorder=3)
                    label = None
                
            if val != -1:
                if not activated:
                    activated = True
                    if activated_time == None: activated_time = time

                if idx == len(activation_times) - 1: line_x_lim = end
                else: line_x_lim = activation_times[idx+1][1]
                ax.plot(convert_units([time, line_x_lim], "steps", self.time_unit, step), [val, val], color=colour, linewidth=linewidth, zorder=3)
            else:
                active_times.append(convert_units([activated_time, time], "steps", self.time_unit, step))
                activated, activated_time = False, None
            
            prev = val

        label = "VSL Activated"
        for ranges in active_times:
            for time in ranges:
                ax.axvline(time, color="grey", alpha=0.2, linestyle='--')
            ax.axvspan(ranges[0], ranges[1], color="grey", alpha=0.1, label=label)
            label = None
        
        edge_ids = list(vsl_data["geometry_data"].keys())
        edge_speeds = [vsl_data["geometry_data"][e_id]["avg_speeds"] for e_id in edge_ids]
        n_edges = len(edge_speeds)
        if avg_geomtry_speeds:
            avg_speeds = []
            for time_idx in range(len(edge_speeds[0])):
                all_pos_vals = [edge_speeds[edge_idx][time_idx] for edge_idx in range(n_edges) if edge_speeds[edge_idx][time_idx] != -1]
                if len(all_pos_vals) == 0: avg_speeds.append(-1)
                else: avg_speeds.append(sum(all_pos_vals) / len(all_pos_vals))

            edge_speeds = [avg_speeds]

        max_speed = max([arr[0] for arr in activation_times])
        for edge_idx, edge in enumerate(edge_speeds):
            if avg_geomtry_speeds: label = "Avg. Edge Speed"
            else: label = "'{0}' Speed".format(edge_ids[edge_idx])
            prev_line = None
            x_vals, y_vals = [], []
            curr_time = start
            for speed_val in edge:
                max_speed = max(max_speed, speed_val)
                if speed_val == -1:
                    if len(x_vals) != 0:
                        if prev_line == None:
                            prev_line, label = ax.plot(convert_units(x_vals, "steps", self.time_unit, step), y_vals, color=self._get_colour("WHEEL", edge_idx==0), label=label, linewidth=1), None
                        else: prev_line = ax.plot(convert_units(x_vals, "steps", self.time_unit, step), y_vals, color=prev_line[0].get_color(), label=label, linewidth=1)
                        x_vals, y_vals = [], []
                else:
                    x_vals.append(curr_time)
                    y_vals.append(speed_val)

                curr_time += step

            if len(x_vals) != 0 and len(y_vals) != 0:
                if prev_line == None: prev_line = ax.plot(convert_units(x_vals, "steps", self.time_unit, step), y_vals, color=self._get_colour("WHEEL", edge_idx==0), label=label, linewidth=1)
                else: prev_line = ax.plot(convert_units(x_vals, "steps", self.time_unit, step), y_vals, color=prev_line[0].get_color(), label=label, linewidth=1)

        if "events" in self.sim_data["data"].keys() and show_events:
            if "completed" in self.sim_data["data"]["events"]:
                self._plot_event(ax)

        y_lim = get_axis_lim(max_speed)
        ax.set_ylim(0, y_lim)
        xlim = convert_units([start, end], "steps", self.time_unit, step)
        if time_range != None: xlim = [max(xlim[0], time_range[0]), min(xlim[1], time_range[1])]
        ax.set_xlim(xlim)

        ax.set_xlabel(default_labels["sim_time"])
        ax.set_ylabel(default_labels["limits"])

        fig_title = "{0}'{1}' Speed Limit and Average Vehicle Speed".format(self.sim_label, vsl_id) if not isinstance(fig_title, str) else fig_title
        ax.set_title(fig_title, pad=20)
        
        box = ax.get_position()
        ax.set_position([box.x0, box.y0 + box.height * 0.02,
                        box.width, box.height * 0.98])

        ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.14),
          fancybox=True, ncol=3)

        fig.tight_layout()

        self._display_figure(save_fig)

    def plot_rg_data(self, rg_id: str, time_range: list|tuple|None=None, show_events: bool=True, line_colour: str|None=None, fig_title: str|None=None, save_fig: str|None=None) -> None:
        """
        Plot how many vehicles are diverted by RG controller.
        :param rg_id:       RG controller ID
        :param show_events: Bool denoting whether to plot when events occur
        :param line_colour: Line colour for plot (defaults to TUD 'blauw')
        :param fig_title:   If given, will overwrite default title
        :param save_fig:    Output image filename, will show image if not given
        """

        if self.simulation != None:
            self.sim_data = self.simulation.__dict__()
            self.units = self.simulation.units.name

        if "controllers" not in self.sim_data["data"].keys():
            desc = "No controllers used during simulation."
            raise_error(KeyError, desc)
        elif rg_id not in self.sim_data["data"]["controllers"].keys():
            desc = "Controller ID '{0}' not found.".format(rg_id)
            raise_error(KeyError, desc)
        
        rg_data = self.sim_data["data"]["controllers"][rg_id]
        if rg_data["type"] != "RG":
            desc = "Controller '{0}' is not a RG controller.".format(rg_id)
            raise_error(ValueError, desc)
        
        start, end, step = rg_data["init_time"], rg_data["curr_time"], self.sim_data["step_len"]
        y_vals = get_cumulative_arr(rg_data["n_diverted"])

        if len(y_vals) == 0:
            desc = "RG controller '{0}' has no data, likely was not activated.".format(rg_id)
            raise_error(ValueError, desc)
        
        fig, ax = plt.subplots(1, 1)

        x_vals = get_time_steps(y_vals, self.time_unit, step, start)
        x_vals, y_vals = limit_vals_by_range(x_vals, y_vals, time_range)
        ax.plot(x_vals, y_vals, color=self.BLAUW, zorder=8, label="Diverted Vehicles")
        ax.set_xlim([x_vals[0], x_vals[-1]])
        y_lim = get_axis_lim(y_vals)
        ax.set_ylim([0, y_lim])
        ax.set_xlabel(default_labels["sim_time"])
        ax.set_ylabel("No. of Diverted Vehicles")
        ax.grid(True, 'both', color='grey', linestyle='-', linewidth=0.5)

        active_times = rg_data["activation_times"]
        label = "RG Activated"
        active_ranges, active = [], False
        for arrs in active_times:
            if not active:
                if arrs[0] != -1:
                    active = True
                    active_ranges.append(arrs[2])
            else:
                if arrs[0] == -1:
                    active = False
                    start_val = active_ranges[-1]
                    active_ranges[-1] = [start_val, arrs[2]]

        
        if isinstance(active_ranges[-1], (int, float)):
            start_val = active_ranges[-1]
            active_ranges[-1] = [start_val, end]

        label = "RG Active"
        for ranges in active_ranges:
            ranges = convert_units(ranges, "steps", self.time_unit, step, start)
            for time in ranges:
                ax.axvline(time * step, color=self.CYAAN, alpha=0.2, linestyle='--')
            ax.axvspan(ranges[0], ranges[1], zorder=6, color=self.CYAAN, alpha=0.5, label=label)
            label=None

        fig_title = "{0}'{1}' Number of Diverted Vehicles".format(self.sim_label, rg_id) if not isinstance(fig_title, str) else fig_title
        ax.set_title(fig_title, pad=20)
        ax.legend()

        if "events" in self.sim_data["data"].keys() and show_events:
            if "completed" in self.sim_data["data"]["events"]:
                self._plot_event(ax)

        fig.tight_layout()

        self._display_figure(save_fig)

    def plot_space_time_diagram(self, edge_ids: list|tuple, upstream_at_top: bool=True, time_range: list|tuple|None=None, fig_title: str|None=None, save_fig: str|None=None) -> None:
        """
        Plot space time data from tracked edge data.
        :param edge_ids:        Single tracked egde ID or list of IDs
        :param upstream_at_top: If true, upstream values are displayed at the top of the diagram
        :param time_range:      Plotting time range (in plotter class units)
        :param fig_title:       If given, will overwrite default title
        :param save_fig:        Output image filename, will show image if not given
        """

        if self.simulation != None:
            self.sim_data = self.simulation.__dict__()
            self.units = self.simulation.units.name

        if "edges" not in self.sim_data["data"].keys():
            desc = "No edges tracked during the simulation."
            raise_error(KeyError, desc)
        
        if not isinstance(edge_ids, (list, tuple)): edge_ids = [edge_ids]

        fig, ax = plt.subplots(1, 1)
        edge_offset = 0

        total_len = sum([self.sim_data["data"]["edges"][e_id]["length"] for e_id in edge_ids])

        if self.units in ["IMPERIAL"]:
            orig_units, new_units = "miles", "miles" if total_len > 1 else "feet"
        elif self.units in ["METRIC", "UK"]:
            orig_units, new_units = "kilometres", "kilometres" if total_len > 1 else "metres"

        x_label, y_label = default_labels["sim_time"], default_labels[new_units]

        if time_range == None: time_range = [-math.inf, math.inf]

        ordered_points = {}
        for e_id in edge_ids:
            if e_id not in self.sim_data["data"]["edges"].keys():
                desc = "Edge '{0}' not found in tracked edges.".format(e_id)
                raise_error(KeyError, desc)
            else: e_data = self.sim_data["data"]["edges"][e_id]

            step_vehicles, edge_length = e_data["step_vehicles"], e_data["length"]
            start, step = e_data["init_time"], self.sim_data["step_len"]

            curr_step = start

            for step_data in step_vehicles:
                curr_time = convert_units(curr_step, "steps", self.time_unit, step)
                if curr_time <= time_range[1] and curr_time >= time_range[0]:
                    for veh_data in step_data:

                        y_val = (veh_data[1] * edge_length) + edge_offset
                        if not upstream_at_top: y_val = total_len - y_val
                        y_val = convert_units(y_val, orig_units, new_units)

                        if curr_step not in ordered_points.keys():
                            ordered_points[curr_step] = [(y_val, veh_data[2])]
                        else: ordered_points[curr_step].append((y_val, veh_data[2]))
                        
                elif curr_time > time_range[1]:
                    break

                curr_step += 1

            edge_offset += edge_length

        idxs = ordered_points.keys()
        x_vals, y_vals, speed_vals = [], [], []
        for idx in idxs:
            x_vals += [convert_units(idx, "steps", self.time_unit, step)] * len(ordered_points[idx])
            dist_speed = ordered_points[idx]
            y_vals += [val[0] for val in dist_speed]
            speed_vals += [val[1] for val in dist_speed]

        if len(x_vals) == 0 or len(y_vals) == 0:
            if time_range == None:
                desc = "No data to plot (no vehicles recorded on edges)."
                raise_error(ValueError, desc)
            else:
                desc = "No data to plot (no vehicles recorded during time frame '{0}-{1}{2}').".format(time_range[0], time_range[1], self.time_unit)
                raise_error(ValueError, desc)
        
        points = ax.scatter(x_vals, y_vals, c=speed_vals, s=0.5, cmap='hot')

        divider = make_axes_locatable(ax)
        cax = divider.append_axes("right", size="5%", pad=0.1)
        plt.colorbar(points, cax=cax, label=default_labels["speed"])

        ax.set_xlim(min(x_vals), max(x_vals))
        ax.set_ylim(0, max(y_vals))
        ax.set_ylabel(y_label)
        ax.set_xlabel(x_label)

        if not isinstance(fig_title, str):
            if len(edge_ids) == 0: e_label = "Edge '{0}'".format(edge_ids[0])
            elif upstream_at_top: e_label = "Edges '{0}' - '{1}'".format(edge_ids[-1], edge_ids[0])
            else: e_label = "Edges '{0}' - '{1}'".format(edge_ids[0], edge_ids[-1])
            fig_title = "{0}{1} Vehicle Speeds and Positions".format(self.sim_label, e_label)

        ax.set_title(fig_title, pad=20)

        fig.tight_layout()

        self._display_figure(save_fig)

    def plot_trajectories(self, edge_ids: list|tuple, vehicle_pct: float=1, rnd_seed: int|None=None, time_range: list|tuple|None=None, show_events: bool=True, line_colour: str|None=None, fig_title: str|None=None, save_fig: str|None=None) -> None:
        """
        Plot vehicle trajectory data from tracked edge data.
        :param edge_ids:    Single tracked egde ID or list of IDs
        :param vehicle_pct: Percent of vehicles plotted (defaults to all)
        :param rnd_seed:    When vehicle_pct < 1, vehicles are selected randomly with rnd_seed
        :param time_range:  Plotting time range (in plotter class units)
        :param show_events: Bool denoting whether to plot when events occur
        :param line_colour: Line colour for plot (defaults to TUD 'blauw')
        :param fig_title:   If given, will overwrite default title
        :param save_fig:    Output image filename, will show image if not given
        """

        if self.simulation != None:
            self.sim_data = self.simulation.__dict__()
            self.units = self.simulation.units.name

        if not isinstance(edge_ids, (list, tuple)): edge_ids = [edge_ids]

        total_len = 0
        if "edges" not in self.sim_data["data"].keys():
            desc = "No edges tracked during the simulation."
            raise_error(KeyError, desc)
        else:
            for edge_id in edge_ids:
                if edge_id in self.sim_data["data"]["edges"].keys():
                    total_len += self.sim_data["data"]["edges"][edge_id]["length"]
                else:
                    desc = "Edge ID '{0}' not found.".format(edge_id)
                    raise_error(KeyError, desc)

        x_lim_time_range = time_range != None
        if time_range == None: time_range = [-math.inf, math.inf]

        seed(rnd_seed)
        line_data, edge_offset, ignore_list = {}, 0, set([])
        step_length = self.sim_data["step_len"]

        for edge_idx, edge_id in enumerate(edge_ids):

            edge_data = self.sim_data["data"]["edges"][edge_id]

            step_vehicle_data, edge_length = edge_data["step_vehicles"], edge_data["length"]
            start = edge_data["init_time"]

            curr_step, first_step = start, True

            for step_vehicles in step_vehicle_data:
                
                curr_time = convert_units(curr_step, "steps", self.time_unit, step_length)
                if curr_time >= time_range[0] and curr_time <= time_range[1]:
                    
                    for vehicle_data in step_vehicles:
                        vehicle_id, vehicle_pos, vehicle_lane = vehicle_data[0], vehicle_data[1], vehicle_data[3]
                    
                        if edge_idx == 0 or first_step:
                            if vehicle_id not in line_data and vehicle_id not in ignore_list:
                                if random() <= vehicle_pct:
                                    line_data[vehicle_id] = {'x': [], 'y': []}
                                else: ignore_list.add(vehicle_id)
                        
                        if vehicle_id in line_data.keys():
                            line_data[vehicle_id]['x'].append(curr_step)
                            line_data[vehicle_id]['y'].append((vehicle_pos * edge_length) + edge_offset)

                    first_step = False

                elif curr_time > time_range[1]:
                    break
                
                curr_step += 1

            edge_offset += edge_length
            
        if self.units in ["IMPERIAL"]:
            orig_units, new_units = "miles", "miles" if total_len > 1 else "feet"
        elif self.units in ["METRIC", "UK"]:
            orig_units, new_units = "kilometres", "kilometres" if total_len > 1 else "metres"
        x_label, y_label = default_labels["sim_time"], default_labels[new_units]

        fig, ax = plt.subplots(1, 1)
        
        lines = []
        x_lim, y_lim = [math.inf, -math.inf], [math.inf, -math.inf]
        for veh_data in line_data.values():
            x = convert_units(veh_data['x'], "steps", self.time_unit, step_length, True)
            if not x_lim_time_range: x_lim = [min(x_lim[0], min(x)), max(x_lim[1], max(x))]
            
            y = convert_units(veh_data['y'], orig_units, new_units, keep_arr=True)
            y_lim = [0, max(y_lim[1], max(y))]
            
            line = ax.plot(x, y, color=self._get_colour(line_colour), linewidth=0.5)
            lines.append(line)

        if len(lines) == 0:
            desc = "No vehicles found within range '[{0}]'. ".format(", ".join([str(val) for val in time_range]))
            raise_error(ValueError, desc)

        if x_lim_time_range: ax.set_xlim(time_range)
        else: ax.set_xlim(x_lim)
        ax.set_ylim(y_lim)
        ax.set_xlabel(x_label)
        ax.set_ylabel(y_label)
        if fig_title == None: fig_title = "Vehicle Trajectories"
        fig_title = self.sim_label + fig_title
        ax.set_title(fig_title, pad=20)

        if "events" in self.sim_data["data"].keys() and show_events:
            if "completed" in self.sim_data["data"]["events"]:
                self._plot_event(ax)

        fig.tight_layout()

        self._display_figure(save_fig)

    def plot_fundamental_diagram(self, edge_ids: list|tuple|str, axes: list|tuple=("density", "flow"), fig_title: str|None=None, save_fig: str|None=None) -> None:

        if self.simulation != None:
            self.sim_data = self.simulation.__dict__()
            self.units = self.simulation.units.name

        if isinstance(edge_ids, str): edge_ids = [edge_ids]
        elif not isinstance(edge_ids, (list, tuple)):
            desc = "Invalid edge_ids '{0}' type (must be '[str|list|tuple]' not '{1}')".format(edge_ids, type(edge_ids).__name__)
            raise_error(TypeError, desc)

        fig, ax = plt.subplots(1, 1)
        all_edge_data = self.sim_data["data"]["edges"]

        for edge_id in edge_ids:
            if edge_id not in all_edge_data.keys():
                desc = "Tracked edge with ID '{0}' not found.".format(edge_id)
                raise_error(KeyError, desc)
            
            e_length = all_edge_data[edge_id]["length"]
            x_points, y_points, e_step_data = [], [], all_edge_data[edge_id]["step_vehicles"]
            for step in e_step_data:
                if len(step) == 0: continue
                else:
                    n_vehicles = len(step)
                    density = n_vehicles / e_length
                    all_speeds = [v[2] for v in step]
                    avg_speed = sum(all_speeds) / len(all_speeds)
                    if self.units == "UK": avg_speed = convert_units(avg_speed, "mph", "kmph")
                    flow = avg_speed * density

                    for idx, (axis, points_arr) in enumerate(zip(axes, [x_points, y_points])):
                        match axis.upper():
                            case "DENSITY":
                                points_arr.append(density)
                            case "FLOW":
                                points_arr.append(flow)
                            case "SPEED":
                                points_arr.append(avg_speed)
                            case _:
                                desc = "Invalid {0}-axis value '{1}' (must be ['density'|'flow'|'speed'])".format("x" if idx == 0 else "y", axis)
                                raise_error(ValueError, desc)

            if len(x_points) > 0 and len(x_points) == len(y_points): plt.scatter(x_points, y_points)

        dist = "mi" if self.units == "IMPERIAL" else "km"
        sp = "mph" if self.units == "IMPERIAL" else "kmph"

        axis_labels = {"DENSITY": "Density (veh/{0})".format(dist),
                        "SPEED": "Average Speed ({0})".format(sp),
                        "FLOW": "Flow (veh/hr)"}
        
        ax.set_title("{0}-{1} Fundamental Diagram".format(axes[0].title(), axes[1].title()), pad=20)
        ax.set_xlabel(axis_labels[axes[0].upper()])
        ax.set_ylabel(axis_labels[axes[1].upper()])

        fig.tight_layout()

        self._display_figure(save_fig)


    def _get_colour(self, colour: str|int|None=None, reset_wheel: bool=False) -> str:

        if reset_wheel: self._next_colour_idx = 0

        if colour == None:
            colour = self.line_colours[0]
        
        elif isinstance(colour, int):
            if self._next_colour_idx >= 0 and self._next_colour_idx < len(self.line_colours):
                colour = self.line_colours[colour]
            else:
                desc = "Colour wheel index '{0}' out of range.".format(self._next_colour_idx)
                raise_error(IndexError, desc)

        elif isinstance(colour, str):
            if colour in tud_colours:
                colour = tud_colours[colour]
            elif colour.upper() == "DEFAULT":
                colour = tud_colours[self._default_colour]
            elif colour.upper() == "RANDOM":
                colour = choice(self.line_colours)
            elif colour.upper() == "WHEEL":
                if self._next_colour_idx >= 0 and self._next_colour_idx < len(self.line_colours):
                    colour = self.line_colours[self._next_colour_idx]
                
                    if self._next_colour_idx == len(self.line_colours) - 1: self._next_colour_idx = 0
                    else: self._next_colour_idx += 1
            
                else:
                    desc = "Colour wheel index '{0}' out of range.".format(self._next_colour_idx)
                    raise_error(IndexError, desc)
            elif not is_mpl_colour(colour):
                desc = "Unrecognised colour '{0}'.".format(colour)
                raise_error(ValueError, desc)

        else:
            desc = "Invalid line_colour '{0}' (must be 'str', not '{1}').".format(colour, type(colour).__name__)
            raise_error(TypeError, desc)
        
        return colour

    def _plot_event(self, ax) -> None:
        """
        Plot events from the simulation data on a given axes.
        :param ax: matplotlib.pyplot.axes object
        """

        _, y_lim = ax.get_xlim(), ax.get_ylim()
        for event in self.sim_data["data"]["events"]["completed"]:
            event_start, event_end = convert_units([event["start_time"], event["end_time"]], "steps", self.time_unit, self.sim_data["step_len"])
            ax.axvspan(event_start, event_end, color="red", zorder=1, alpha=0.2)

            ax.axvline(event_start, color="red", alpha=0.4, linestyle='--')
            ax.axvline(event_end, color="red", alpha=0.4, linestyle='--')

            ax.text(event_start + ((event_end - event_start)/2), y_lim[1] * 0.9, event["id"], horizontalalignment='center', color="red", zorder=10)
