"""Write depmod rows accepted by Android libmodprobe's literal-space parser."""


def parse_dependencies(text):
    result = {}
    for line in text.split('\n'):
        if not line or line.startswith('#'):
            continue
        # Match ModuleConfig::ParseCfg: Split(line, " ") retains empty fields.
        fields = line.split(' ')
        if any(not item or any(c.isspace() for c in item) for item in fields):
            raise ValueError(f'Empty or malformed Android dependency token: {line!r}')
        if not fields[0].endswith('.ko:'):
            raise ValueError(f'Malformed module dependency owner: {line!r}')
        owner = fields[0][:-1]
        if owner in result or any(not item.endswith('.ko') for item in fields[1:]):
            raise ValueError(f'Duplicate owner or malformed dependency: {line!r}')
        result[owner] = fields[1:]
    return result


def format_dependency(owner, dependencies):
    # A dependency-free module must end at ':', never ': '.
    line = ' '.join([owner + ':', *dependencies])
    parse_dependencies(line)
    return line
