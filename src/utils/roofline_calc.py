##############################################################################bl
# MIT License
#
# Copyright (c) 2021 - 2025 Advanced Micro Devices, Inc. All Rights Reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
##############################################################################el

import csv
from dataclasses import dataclass
from pathlib import Path

from utils.logger import console_debug, console_error, console_warning
from utils.roofline_config import load_roofline_config, evaluate_equation

################################################
# Global vars
################################################

IMGNAME = "empirRoof"

XMIN = 0.01
XMAX = 1000

FONT_SIZE = 16
FONT_COLOR = "black"
FONT_WEIGHT = "bold"

PEAK_OPS_DATATYPES = ["FP8", "FP16", "BF16", "FP32", "FP64", "I8", "I32", "I64"]
MFMA_DATATYPES = ["FP4", "FP6", "FP8", "FP16", "BF16", "FP32", "FP64", "I8"]

TOP_N = 10


################################################
# Helper funcs
################################################
@dataclass
class AI_Data:
    KernelName: str
    numCalls: float

    total_flops: float
    valu_flops: float
    mfma_flops_f6f4: float
    mfma_flops_f8: float
    mfma_flops_f16: float
    mfma_flops_bf16: float
    mfma_flops_f32: float
    mfma_flops_f64: float
    mfma_iops_i8: float
    lds_data: float
    L1cache_data: float
    L2cache_data: float
    hbm_data: float

    totalDuration: float
    avgDuration: float


def get_font():
    return {
        "size": FONT_SIZE,
        "color": FONT_COLOR,
        "weight": FONT_WEIGHT,
        "family": "serif",
    }


def get_color(catagory):
    if catagory == "ai_l1":
        return "green"
    elif catagory == "ai_l2":
        return "blue"
    elif catagory == "ai_hbm":
        return "red"
    else:
        raise RuntimeError("Invalid catagory passed to get_color()")


# -------------------------------------------------------------------------------------
#                           Plot BW at each cache level
# -------------------------------------------------------------------------------------
def calc_ceilings(roofline_parameters, dtype, benchmark_data):
    """Given benchmarking data, calculate ceilings (or peak performance) for empirical roofline"""
    # TODO: This is where filtering by memory level will need to occur for standalone
    graphPoints = {"hbm": [], "l2": [], "l1": [], "lds": [], "valu": [], "mfma": []}

    if roofline_parameters["mem_level"] == "ALL":
        cacheHierarchy = ["HBM", "L2", "L1", "LDS"]
    else:
        cacheHierarchy = roofline_parameters["mem_level"]

    x1 = y1 = x2 = y2 = -1
    x1_mfma = y1_mfma = x2_mfma = y2_mfma = -1

    ops_flops = "Ops" if (dtype[:1] == "I") else "Flops"

    if dtype in PEAK_OPS_DATATYPES:
        peakOps = float(
            benchmark_data[dtype + "{}".format(ops_flops)][
                roofline_parameters["device_id"]
            ]
        )
    for i in range(0, len(cacheHierarchy)):
        # Plot BW line
        console_debug("roofline", "Current cache level is %s" % cacheHierarchy[i])
        curr_bw = cacheHierarchy[i] + "Bw"
        peakBw = float(benchmark_data[curr_bw][roofline_parameters["device_id"]])

        x1 = float(XMIN)
        y1 = float(XMIN) * peakBw

        if dtype in PEAK_OPS_DATATYPES:
            x2 = peakOps / peakBw
            y2 = peakOps

            # Plot MFMA lines (NOTE: Assuming MI200 soc)
            x1_mfma = peakOps / peakBw
            y1_mfma = peakOps

        if dtype in MFMA_DATATYPES:
            target_precision = (dtype) if (dtype[:1] == "I") else ("F" + dtype[2:])

            peakMFMA = float(
                benchmark_data["MFMA{}{}".format(target_precision, ops_flops)][
                    roofline_parameters["device_id"]
                ]
            )
            x2_mfma = peakMFMA / peakBw
            y2_mfma = peakMFMA

        # Check which peak is higher for formatting bandwidth lines
        if y2_mfma > y1_mfma:  # peakMFMA
            peakX = x2_mfma
            peakY = y2_mfma
        else:  # peakVALU
            peakX = x1_mfma
            peakY = y1_mfma

        # These are the points to use:
        console_debug("roofline", "coordinate points:")
        console_debug("x = [{}, {}]".format(x1, peakX))
        console_debug("y = [{}, {}]".format(y1, peakY))

        graphPoints[cacheHierarchy[i].lower()].append([x1, peakX])
        graphPoints[cacheHierarchy[i].lower()].append([y1, peakY])
        graphPoints[cacheHierarchy[i].lower()].append(peakBw)

    # -------------------------------------------------------------------------------------
    #                                     Plot computing roof
    # -------------------------------------------------------------------------------------
    if dtype in PEAK_OPS_DATATYPES:
        # Plot FMA roof
        x0 = XMAX
        if x2 < x0:
            x0 = x2

        console_debug("FMA ROOF [{}, {}], [{},{}]".format(x0, XMAX, peakOps, peakOps))
        graphPoints["valu"].append([x0, XMAX])
        graphPoints["valu"].append([peakOps, peakOps])
        graphPoints["valu"].append(peakOps)

    # Plot MFMA roof
    if dtype in MFMA_DATATYPES:  # assert that mfma has been assigned
        x0_mfma = XMAX
        if x2_mfma < x0_mfma:
            x0_mfma = x2_mfma

        console_debug(
            "MFMA ROOF [{}, {}], [{},{}]".format(x0_mfma, XMAX, peakMFMA, peakMFMA)
        )
        graphPoints["mfma"].append([x0_mfma, XMAX])
        graphPoints["mfma"].append([peakMFMA, peakMFMA])
        graphPoints["mfma"].append(peakMFMA)

    return graphPoints


# -------------------------------------------------------------------------------------
#                              Overlay application performance
# -------------------------------------------------------------------------------------
# Calculate relevant metrics for ai calculation
def calc_ai(mspec, sort_type, ret_df, config_dir):
    """
    Given counter data, calculate arithmetic intensity for each kernel by evaluating
    equations from the architecture-specific roofline configuration file.
    """
    df = ret_df["pmc_perf"]
    df = df.sort_values(by=["Kernel_Name"]).reset_index(drop=True)

    try:
        config = load_roofline_config(mspec.gpu_arch, config_dir)
    except Exception as e:
        console_error(f"Fatal error during roofline configuration for {mspec.gpu_arch}: {e}. Aborting AI calculation.")
        return {"ai_l1": [], "ai_l2": [], "ai_hbm": [], "kernelNames": []}

    myList = []
    
    accumulators = {
        'total_flops': 0.0, 'valu_flops': 0.0, 'mfma_flops_f6f4': 0.0,
        'mfma_flops_f8': 0.0, 'mfma_flops_f16': 0.0, 'mfma_flops_bf16': 0.0,
        'mfma_flops_f32': 0.0, 'mfma_flops_f64': 0.0, 'mfma_iops_i8': 0.0,
        'lds_data': 0.0, 'L1cache_data': 0.0, 'L2cache_data': 0.0,
        'hbm_data': 0.0, 'calls': 0, 'totalDuration': 0.0, 'avgDuration': 0.0
    }

    def reset_accumulators():
        for key in accumulators:
            accumulators[key] = 0.0 if isinstance(accumulators[key], float) else 0

    current_kernel_name = ""
    for idx, row in df.iterrows():
        next_kernel_name = df["Kernel_Name"][idx + 1] if idx + 1 < df.shape[0] else ""
        kernelName = row["Kernel_Name"]
        if not current_kernel_name:
            current_kernel_name = kernelName
            
        pmc_values = row.to_dict()
        dispatch_values = {}

        for key, eq_str in config['arithmetic_intensity_equations'].items():
            if key not in accumulators: continue
            
            is_fp8_eq = key in ['total_flops_fp8_addition', 'mfma_flops_f8']
            is_fp4_fp6_eq = key in ['total_flops_fp4_fp6_addition', 'mfma_flops_f6f4']
            
            if is_fp8_eq and "FP8" not in config['supported_datatypes']: continue
            if is_fp4_fp6_eq and not ("FP4" in config['supported_datatypes'] or "FP6" in config['supported_datatypes']): continue

            dispatch_values[key] = evaluate_equation(eq_str, pmc_values, mspec, config['calc_ai_constants'])

        total_flops = dispatch_values.get('total_flops_base', 0.0)
        total_flops += dispatch_values.get('total_flops_fp8_addition', 0.0)
        total_flops += dispatch_values.get('total_flops_fp4_fp6_addition', 0.0)
        dispatch_values['total_flops'] = total_flops

        for key, value in dispatch_values.items():
            if key in accumulators:
                accumulators[key] += value
        
        duration = pmc_values.get('End_Timestamp', 0) - pmc_values.get('Start_Timestamp', 0)
        accumulators['totalDuration'] += duration
        accumulators['avgDuration'] += duration
        accumulators['calls'] += 1

        at_end = (idx + 1 == df.shape[0])

        if sort_type == "kernels" and (at_end or kernelName != next_kernel_name):
            calls = accumulators['calls'] if accumulators['calls'] > 0 else 1.0
            myList.append(AI_Data(
                KernelName=kernelName, numCalls=accumulators['calls'],
                total_flops=accumulators['total_flops'] / calls,
                valu_flops=accumulators['valu_flops'] / calls,
                mfma_flops_f6f4=accumulators['mfma_flops_f6f4'] / calls,
                mfma_flops_f8=accumulators['mfma_flops_f8'] / calls,
                mfma_flops_f16=accumulators['mfma_flops_f16'] / calls,
                mfma_flops_bf16=accumulators['mfma_flops_bf16'] / calls,
                mfma_flops_f32=accumulators['mfma_flops_f32'] / calls,
                mfma_flops_f64=accumulators['mfma_flops_f64'] / calls,
                mfma_iops_i8=accumulators['mfma_iops_i8'] / calls,
                lds_data=accumulators['lds_data'] / calls,
                L1cache_data=accumulators['L1cache_data'] / calls,
                L2cache_data=accumulators['L2cache_data'] / calls,
                hbm_data=accumulators['hbm_data'] / calls,
                totalDuration=accumulators['totalDuration'],
                avgDuration=accumulators['avgDuration'] / calls
            ))
            reset_accumulators()
            current_kernel_name = next_kernel_name

        if sort_type == "dispatches":
            myList.append(AI_Data(
                KernelName=kernelName, numCalls=1,
                total_flops=accumulators['total_flops'],
                valu_flops=accumulators['valu_flops'],
                mfma_flops_f6f4=accumulators['mfma_flops_f6f4'],
                mfma_flops_f8=accumulators['mfma_flops_f8'],
                mfma_flops_f16=accumulators['mfma_flops_f16'],
                mfma_flops_bf16=accumulators['mfma_flops_bf16'],
                mfma_flops_f32=accumulators['mfma_flops_f32'],
                mfma_flops_f64=accumulators['mfma_flops_f64'],
                mfma_iops_i8=accumulators['mfma_iops_i8'],
                lds_data=accumulators['lds_data'],
                L1cache_data=accumulators['L1cache_data'],
                L2cache_data=accumulators['L2cache_data'],
                hbm_data=accumulators['hbm_data'],
                totalDuration=accumulators['totalDuration'],
                avgDuration=accumulators['avgDuration']
            ))
            reset_accumulators()

    myList.sort(key=lambda x: x.totalDuration, reverse=True)

    intensities = {"ai_l1": [], "ai_l2": [], "ai_hbm": []}
    curr_perf = []
    kernelNames = []
    i = 0
    # Create list of top 5 intensities
    while i < TOP_N and i != len(myList):
        if myList[i].total_flops == 0:
            console_debug(
                "No flops counted for {}, arithmetic intensities will not display on plots.".format(
                    myList[i].KernelName
                )
            )

        kernelNames.append(myList[i].KernelName)
        (
            intensities["ai_l1"].append(myList[i].total_flops / myList[i].L1cache_data)
            if myList[i].L1cache_data
            else intensities["ai_l1"].append(0)
        )
        # print("cur_ai_L1", myList[i].total_flops/myList[i].L1cache_data) if myList[i].L1cache_data else print("null")
        # print()
        (
            intensities["ai_l2"].append(myList[i].total_flops / myList[i].L2cache_data)
            if myList[i].L2cache_data
            else intensities["ai_l2"].append(0)
        )
        # print("cur_ai_L2", myList[i].total_flops/myList[i].L2cache_data) if myList[i].L2cache_data else print("null")
        # print()
        (
            intensities["ai_hbm"].append(myList[i].total_flops / myList[i].hbm_data)
            if myList[i].hbm_data
            else intensities["ai_hbm"].append(0)
        )
        # print("cur_ai_hbm", myList[i].total_flops/myList[i].hbm_data) if myList[i].hbm_data else print("null")
        # print()
        (
            curr_perf.append(myList[i].total_flops / myList[i].avgDuration)
            if myList[i].avgDuration
            else curr_perf.append(0)
        )
        # print("cur_perf", myList[i].total_flops/myList[i].avgDuration) if myList[i].avgDuration else print("null")

        i += 1

    intensityPoints = {"ai_l1": [], "ai_l2": [], "ai_hbm": []}

    for i in intensities:
        values = intensities[i]

        color = get_color(i)
        x = []
        y = []
        for entryIndx in range(0, len(values)):
            x.append(values[entryIndx])
            y.append(curr_perf[entryIndx])

        intensityPoints[i].append(x)
        intensityPoints[i].append(y)

    # Add an entry for kernel names
    intensityPoints["kernelNames"] = kernelNames

    return intensityPoints


def constuct_roof(roofline_parameters, dtype):
    workload_dir = roofline_parameters.get("workload_dir")
    if isinstance(workload_dir, list):
        base_dir = (
            workload_dir[0][0]
            if isinstance(workload_dir[0], (list, tuple))
            else workload_dir[0]
        )
    else:
        base_dir = workload_dir

    benchmark_results = str(Path(base_dir) / "roofline.csv")

    # -----------------------------------------------------
    # Initialize roofline data dictionary from roofline.csv
    # -----------------------------------------------------
    benchmark_data = (
        {}
    )  # TODO: consider changing this to an ordered dict for consistency over py versions
    headers = []
    try:
        with open(benchmark_results, "r") as csvfile:
            csvReader = csv.reader(csvfile, delimiter=",")
            rowCount = 0
            for row in csvReader:
                row.pop(0)  # remove devID
                if rowCount == 0:
                    headers = row
                    for i in headers:
                        benchmark_data[i] = []
                else:
                    for i, key in enumerate(headers):
                        benchmark_data[key].append(row[i])

                rowCount += 1
        csvfile.close()
    except:
        graphPoints = {
            "hbm": [None, None, None],
            "l2": [None, None, None],
            "l1": [None, None, None],
            "lds": [None, None, None],
            "valu": [None, None, None],
            "mfma": [None, None, None],
        }
        return graphPoints

    # ------------------
    #  Generate Roofline
    # ------------------
    results = calc_ceilings(roofline_parameters, dtype, benchmark_data)

    return results
