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

import re
import yaml
from pathlib import Path
from utils.logger import console_error, console_warning

_config_cache = {}

def _validate_roofline_config(config, arch):
    """A private helper to validate the structure and consistency of a loaded config."""
    required_keys = ['supported_datatypes', 'performance_counters', 'calc_ai_constants', 'arithmetic_intensity_equations']
    for key in required_keys:
        if key not in config:
            raise KeyError(f"Missing required key '{key}' in roofline config for {arch}.")

    declared_counters = set(config['performance_counters'])
    used_counters = set()
    for eq_string in config['arithmetic_intensity_equations'].values():
        temp_str = re.sub(r'\$[cm]\.[a-zA-Z0-9_]+', '', eq_string)
        used_counters.update(re.findall(r'[A-Z][A-Z0-9_]+', temp_str))
    
    used_but_not_declared = used_counters - declared_counters
    declared_but_not_used = declared_counters - used_counters - {"End_Timestamp", "Start_Timestamp", "Kernel_Name"}

    if used_but_not_declared:
        console_warning(f"Config validation for {arch}: The following counters are USED in equations but NOT DECLARED in performance_counters: {sorted(list(used_but_not_declared))}")
    
    if declared_but_not_used:
        console_warning(f"Config validation for {arch}: The following counters are DECLARED in performance_counters but NOT USED in any equation: {sorted(list(declared_but_not_used))}")

def load_roofline_config(arch, config_dir):
    """
    Loads and validates the roofline configuration YAML for a given architecture.
    Caches the result to avoid redundant file I/O.
    """
    cache_key = (arch, str(config_dir))
    if cache_key in _config_cache:
        return _config_cache[cache_key]

    config_path = Path(config_dir).joinpath(arch, "0400_roofline_info.yaml")

    try:
        with open(config_path, "r") as f:
            parsed_yaml = yaml.safe_load(f)
    except FileNotFoundError:
        console_error(f"Roofline config file not found for architecture '{arch}' at: {config_path}")
        raise
    except yaml.YAMLError as e:
        console_error(f"Error parsing YAML file {config_path}: {e}")
        raise

    try:
        config = parsed_yaml['Panel Config']['data source'][0]['roofline_config']
        _validate_roofline_config(config, arch)
        
        _config_cache[cache_key] = config
        return config
    except (KeyError, TypeError, IndexError) as e:
        console_error(f"Invalid structure in roofline config file {config_path}. Could not navigate to 'roofline_config'. Error: {e}")
        raise

def evaluate_equation(equation_string, pmc_data, mspec, constants_dict):
    """
    Evaluates a single equation string by substituting constants and evaluating against PMC data.
    """
    if not isinstance(equation_string, str) or not equation_string:
        return 0.0

    def replacer(match):
        prefix = match.group(1)
        name = match.group(2)
        if prefix == 'c':
            if name in constants_dict:
                return str(constants_dict[name])
            else:
                raise KeyError(f"Constant '$c.{name}' not found in calc_ai_constants.")
        elif prefix == 'm':
            if hasattr(mspec, name):
                return str(getattr(mspec, name))
            else:
                raise AttributeError(f"Attribute '$m.{name}' not found in mspec object.")
        return match.group(0)

    try:
        substituted_str = re.sub(r'\$([cm])\.([a-zA-Z0-9_]+)', replacer, equation_string)
        substituted_str = re.sub(r'#.*', '', substituted_str).strip()
        
        required_pmcs = set(re.findall(r'[A-Z][A-Z0-9_]+', substituted_str))
        eval_locals = {pmc: pmc_data.get(pmc, 0) for pmc in required_pmcs}
        
        result = eval(substituted_str, {"__builtins__": {}}, eval_locals)
        return float(result)
    except Exception as e:
        console_warning(f"Could not evaluate roofline equation. Error: {e}")
        console_warning(f"  Original Equation: {equation_string}")
        console_warning(f"  Substituted: {substituted_str if 'substituted_str' in locals() else 'Substitution Failed'}")
        return 0.0
