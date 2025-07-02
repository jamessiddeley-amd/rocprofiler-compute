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

def load_roofline_config(arch, config_dir):
    """
    Loads the roofline configuration YAML for a given architecture.
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
        _config_cache[cache_key] = config
        return config
    except (KeyError, TypeError, IndexError) as e:
        console_error(f"Invalid structure in roofline config file {config_path}. Error: {e}")
        raise

def evaluate_equation(equation_string, pmc_data, mspec, constants_dict):
    """
    Evaluates an equation string. Handles substitution and aggregation of raw counters.
    """
    if not isinstance(equation_string, str) or not equation_string:
        return 0.0

    def replacer(match):
        prefix, name = match.groups()
        if prefix == 'c':
            return str(constants_dict.get(name, ''))
        elif prefix == 'm':
            return str(getattr(mspec, name, ''))
        return match.group(0)

    try:
        # substitute $c. and $m. constants
        substituted_str = re.sub(r'\$([cm])\.([a-zA-Z0-9_]+)', replacer, equation_string)
        substituted_str = re.sub(r'#.*', '', substituted_str).strip()

        # find all potential variables (PMC names) in the equation
        required_pmcs = set(re.findall(r'\b[A-Z][A-Z0-9_]*[A-Z0-9](?:_sum)?\b', substituted_str))
        
        eval_locals = {}
        for pmc_name in required_pmcs:
            if pmc_name.endswith('_sum'):
                base_name = pmc_name[:-4]
                raw_counters = [key for key in pmc_data.keys() if key.startswith(base_name)]
                total_value = sum(pmc_data.get(raw_key, 0) for raw_key in raw_counters)
                eval_locals[pmc_name] = total_value
            else:
                eval_locals[pmc_name] = pmc_data.get(pmc_name, 0)

        result = eval(substituted_str, {"__builtins__": {}}, eval_locals)
        return float(result)

    except Exception as e:
        console_warning(f"Could not evaluate roofline equation. Error: {e}")
        console_warning(f"  Original Equation: {equation_string}")
        return 0.0