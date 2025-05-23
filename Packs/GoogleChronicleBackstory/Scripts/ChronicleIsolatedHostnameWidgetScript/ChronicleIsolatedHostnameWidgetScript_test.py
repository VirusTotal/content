from unittest.mock import patch

import ChronicleIsolatedHostnameWidgetScript
import demistomock as demisto

DUMMY_HOSTNAME = "dummyhost.com"
INDICATOR_DATA = {"indicator": {"CustomFields": {"chronicleassethostname": DUMMY_HOSTNAME, "chronicleisolatedhostname": "No"}}}


def test_main_success(mocker):
    """
    When main function is called, get_html_representation should be called.
    """

    mocker.patch.object(demisto, "args", return_value=INDICATOR_DATA)
    mocker.patch.object(ChronicleIsolatedHostnameWidgetScript, "get_html_representation", return_value="")
    ChronicleIsolatedHostnameWidgetScript.main()
    assert ChronicleIsolatedHostnameWidgetScript.get_html_representation.called


@patch("ChronicleIsolatedHostnameWidgetScript.return_error")
def test_main_failure(mock_return_error, capfd, mocker):
    """
    When main function gets some exception then valid message should be printed.
    """

    mocker.patch.object(demisto, "args", return_value=INDICATOR_DATA)
    mocker.patch.object(ChronicleIsolatedHostnameWidgetScript, "get_html_representation", side_effect=Exception)
    with capfd.disabled():
        ChronicleIsolatedHostnameWidgetScript.main()

    mock_return_error.assert_called_once_with("Could not load widget:\n")


def test_get_html_representation_when_no_hostname_is_attached():
    """
    When no hostname is attached, get_html_representation should return html representation accordingly.
    """

    html_representation = ChronicleIsolatedHostnameWidgetScript.get_html_representation("", "No")
    assert (
        html_representation
        == "<div style='color:grey; text-align:center;'><h1>No Hostname associated with the ChronicleAsset</h1></div>"
    )


def test_get_html_representation_when_hostname_is_not_isolated():
    """
    When hostname is not isolated, get_html_representation should return html representation accordingly.
    """

    html_representation = ChronicleIsolatedHostnameWidgetScript.get_html_representation(DUMMY_HOSTNAME, "No")
    assert (
        html_representation == "<div style='color:green; text-align:center;'><h1>dummyhost.com<br/>Hostname Not Isolated</h1>"
        "</div>"
    )


def test_get_html_representation_when_hostname_is_potentially_isolated():
    """
    When hostname is potentially isolated, get_html_representation should return html representation accordingly.
    """

    html_representation = ChronicleIsolatedHostnameWidgetScript.get_html_representation(DUMMY_HOSTNAME, "Yes")
    assert html_representation == "<div style='color:red; text-align:center;'><h1>dummyhost.com<br/>Hostname Isolated</h1></div>"
