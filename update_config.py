#!/usr/bin/env python3
"""
Script to add environment variable substitution to config.py
"""

with open('src/coding_agent/config.py', 'r') as f:
    content = f.read()

# 1. Add imports after 'import yaml'
content = content.replace(
    'import yaml',
    'import yaml\nimport re\nimport os'
)

# 2. Add the _substitute_env_vars function after the imports section
# Find the "# ──────────────────────────────────────────────────────────────" line after imports
import_end_marker = '# ──────────────────────────────────────────────────────────────\n# Configuration dataclasses'
substitute_func = '''
def _substitute_env_vars(data: Any) -> Any:
    """Recursively substitute ${ENV_VAR} placeholders with environment variable values."""
    if isinstance(data, str):
        def replace(match):
            var_name = match.group(1)
            return os.environ.get(var_name, match.group(0))
        return re.sub(r"\\${([^}]+)}", replace, data)
    elif isinstance(data, dict):
        return {k: _substitute_env_vars(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_substitute_env_vars(item) for item in data]
    return data

'''

content = content.replace(import_end_marker, substitute_func + import_end_marker)

# 3. Update _load_yaml to use _substitute_env_vars
old_load_yaml = '''def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file, returning an empty dict if it doesn't exist."""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}'''

new_load_yaml = '''def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file, returning an empty dict if it doesn't exist."""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data = data if isinstance(data, dict) else {}
    # Substitute environment variable placeholders
    return _substitute_env_vars(data)'''

content = content.replace(old_load_yaml, new_load_yaml)

# Also update the resolution order comment
content = content.replace(
    'Resolution order (later wins):\n    base.yaml  →  model-specific YAML  →  CLI overrides',
    'Resolution order (later wins):\n    base.yaml  →  model-specific YAML  →  CLI overrides  →  Environment variables (${VAR} placeholders)'
)

with open('src/coding_agent/config.py', 'w') as f:
    f.write(content)

print("Successfully updated config.py")
