"""Find kernel failures without matching harmless ramoops/debug driver names."""
import re

ERROR = re.compile(
    r'Unknown symbol|disagrees about version|invalid module format|'
    r'module verification failed|BTF mismatch|'
    r'(?<![A-Za-z0-9_])BUG:|(?<![A-Za-z0-9_])Oops:|Kernel panic', re.I)


def kernel_errors(text):
    return [line for line in text.splitlines() if ERROR.search(line)]
