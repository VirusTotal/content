import re

import demistomock as demisto
import requests
from CommonServerPython import *
from pkg_resources import parse_version

from CommonServerUserPython import *

ACCEPT_HEADER = {
    "Accept": "application/json, "
    "application/vnd.docker.distribution.manifest.v2+json, "
    "application/vnd.docker.distribution.manifest.list.v2+json"
}

# use 10 seconds timeout for requests
TIMEOUT = 10
DEFAULT_REGISTRY = "registry-1.docker.io"


def parse_www_auth(www_auth):
    """Parse realm and service from www-authenticate string of the form:
    Bearer realm="https://auth.docker.io/token",service="registry.docker.io"

    :param www_auth: www-authenticate header value
    :type www_auth: string
    """
    match = re.match(r'.*realm="(.+)",service="(.+)".*', www_auth, re.IGNORECASE)
    if not match:
        return None
    return (match.group(1), match.group(2))


def docker_auth(image_name, verify_ssl=True, registry=DEFAULT_REGISTRY, gateway_creds=""):
    """
    Authenticate to the docker service. Return an authentication token if authentication is required.
    """
    res = requests.get(f"https://{registry}/v2/", headers=ACCEPT_HEADER, timeout=TIMEOUT, verify=verify_ssl)
    if res.status_code == 401:  # need to authenticate
        # defaults in case we fail for some reason
        realm = "https://auth.docker.io/token"
        service = "registry.docker.io"
        # Should contain header: Www-Authenticate
        www_auth = res.headers.get("www-authenticate")
        if www_auth:
            parse_auth = parse_www_auth(www_auth)
            if parse_auth:
                realm, service = parse_auth
            else:
                demisto.info(f"Failed parsing www-authenticate header: {www_auth}")
        else:
            demisto.info(f"Failed extracting www-authenticate header from registry: {registry}, final url: {res.url}")
        headers = ACCEPT_HEADER.copy()
        if gateway_creds and registry != DEFAULT_REGISTRY:
            headers["Authorization"] = f"Basic {gateway_creds}"
        res = requests.get(
            f"{realm}?scope=repository:{image_name}:pull&service={service}", headers=headers, timeout=TIMEOUT, verify=verify_ssl
        )
        res.raise_for_status()
        res_json = res.json()
        return res_json.get("token")
    else:
        res.raise_for_status()
        return None


def clear_non_numbered_tags(tags):
    """Clears a given tags list to only keep numbered tags

    Args:
        tags(list): list of docker image tag names - ordered in lexical order

    Returns:
        a tag list with only numbered tags
    """
    only_numbered_tags = []
    for tag in tags:
        number_token = 1
        split_tag = tag.split(".")
        for sub_section in split_tag:
            if not sub_section.isdigit():
                number_token = 0

        if number_token:
            only_numbered_tags.append(tag)

    return only_numbered_tags


def lexical_find_latest_tag(tags):
    """Will return the latest numeric docker image tag if possible - otherwise will return the last lexical tag.

    for example for the tag list: [2.0.2000, 2.1.2700 2.1.373, latest], will return 2.1.2700

    Args:
        tags(list): list of docker image tag names - ordered in lexical order
    """

    only_numbered_tags = clear_non_numbered_tags(tags)

    if len(only_numbered_tags) == 0:
        return tags[-1]

    max_tag = only_numbered_tags[0]

    for num_tag in only_numbered_tags:
        if parse_version(max_tag) < parse_version(num_tag):
            max_tag = num_tag

    return max_tag


def find_latest_tag_by_date(tags):
    """Get the latest tags by datetime comparison.

    Args:
        tags(list): List of dictionaries representing the docker image tags

    Returns:
        The last updated docker image tag name
    """
    latest_tag_name = "latest"
    latest_tag_date = datetime.now() - timedelta(days=400000)
    for tag in tags:
        tag_date = datetime.strptime(tag.get("last_updated"), "%Y-%m-%dT%H:%M:%S.%fZ")
        if tag_date >= latest_tag_date:
            latest_tag_date = tag_date
            latest_tag_name = tag.get("name")

    return latest_tag_name


def main():
    if demisto.args().get("use_system_proxy") == "no":
        del os.environ["HTTP_PROXY"]
        del os.environ["HTTPS_PROXY"]
        del os.environ["http_proxy"]
        del os.environ["https_proxy"]
    verify_ssl = demisto.args().get("trust_any_certificate") != "yes"
    docker_full_name = demisto.args()["docker_image"]
    gateway_creds = demisto.args().get("creds_for_opp", "")
    registry = DEFAULT_REGISTRY
    image_name = docker_full_name
    if docker_full_name.count("/") > 1:
        registry, image_name = docker_full_name.split("/", 1)
    try:
        auth_token = docker_auth(image_name, verify_ssl, registry, gateway_creds)
        headers = ACCEPT_HEADER.copy()
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        # first try to get the docker image tags using normal http request
        res = requests.get(
            url=f"https://hub.docker.com/v2/repositories/{image_name}/tags",
            verify=verify_ssl,
        )
        if res.status_code == 200:
            tags = res.json().get("results", [])
            # if http request successful find the latest tag by date in the response
            if tags:
                tag = find_latest_tag_by_date(tags)
            else:
                tag = ""
                demisto.debug(f"No tags, {tag=}")

        else:
            # if http request did not successed than get tags using the API.
            # See: https://docs.docker.com/registry/spec/api/#listing-image-tags
            res = requests.get(
                f"https://{registry}/v2/{image_name}/tags/list", headers=headers, timeout=TIMEOUT, verify=verify_ssl
            )
            res.raise_for_status()
            # the API returns tags in lexical order with no date info - so try an get the numeric highest tag
            tags = res.json().get("tags", [])
            if tags:
                tag = lexical_find_latest_tag(tags)
            else:
                tag = ""
                demisto.debug(f"No tags, {tag=}")

        demisto.results(tag)
    except Exception as ex:
        return_error(f"Failed getting tag for: {docker_full_name}. Err: {ex!s}")


# python2 uses __builtin__ python3 uses builtins
if __name__ in ("__main__", "__builtin__", "builtins"):
    main()
