#!/usr/bin/env python3
with open('src/coding_agent/config.py', 'r') as f:
    lines = f.readlines()

# Find the line after 'import yaml'
insert_index = None
for i, line in enumerate(lines):
    if line.strip() == 'import yaml':
        insert_index = i + 1
        break

if insert_index is not None:
    new_lines = [
        'import re\n',
        'import os\n',
        '\n',
        'def _substitute_env_vars(data: Any) -> Any:\n',
        '    """Recursively substitute ${ENV_VAR} placeholders with environment variable values."""\n',
        '    if isinstance(data, str):\n',
        '        def replace(match):\n',
        '            var_name = match.group(1)\n',
        '            return os.environ.get(var_name, match.group(0))\n',
        '        return re.sub(r"\\${([^}]+)}", replace, data)\n',
        '    elif isinstance(data, dict):\n',
        '        return {k: _substitute_env_vars(v) for k, v in data.items()}\n',
        '    elif isinstance(data, list):\n',
        '        return [_substitute_env_vars(item) for item in data]\n',
        '    return data\n',
        '\n',
    ]
    for i, line in enumerate(new_lines):
        lines.insert(insert_index + i, line)

    with open('src/coding_agent/config.py', 'w') as f:
        f.writelines(lines)
    print('Added _substitute_env_vars function and imports')
