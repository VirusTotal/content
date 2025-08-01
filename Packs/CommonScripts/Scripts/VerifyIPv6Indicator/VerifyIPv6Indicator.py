from ipaddress import IPv6Address

import demistomock as demisto
from CommonServerPython import *


def is_valid_ipv6_address(address):
    try:
        IPv6Address(address)
        return True
    except ValueError:
        return False


def main():
    the_input = demisto.args().get("input")
    the_input = argToList(the_input)
    entries_list = []

    for item in the_input:
        demisto.info(f"Got IPv6 {item}")

        if re.match(r"(?i)^[g-z]", item):
            # Can't be an actual IPv6, invalid chars, dropping
            entries_list.append("")
            continue

        else:
            item = re.sub("[^a-f0-9:%th.]+", "", item)  # Remove leading char caught as part of the regex
            demisto.info(f"Changed item to {item!s}")

        if is_valid_ipv6_address(item):
            entries_list.append(item)
        else:
            entries_list.append("")

    if entries_list:
        return_results(entries_list)
    else:
        return_results("")


# python2 uses __builtin__ python3 uses builtins
if __name__ == "__builtin__" or __name__ == "builtins":
    main()
