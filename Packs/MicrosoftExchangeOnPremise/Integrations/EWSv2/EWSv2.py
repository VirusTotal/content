import email
import hashlib
from email.policy import SMTP, SMTPUTF8
from io import StringIO
from multiprocessing import Process

import dateparser  # type: ignore
import exchangelib
from CommonServerPython import *
from EWSApiModule import *
from exchangelib import (
    BASIC,
    DELEGATE,
    DIGEST,
    IMPERSONATION,
    NTLM,
    Body,
    EWSDateTime,
    EWSTimeZone,
    FileAttachment,
    FolderCollection,
    HTMLBody,
    ItemAttachment,
    Version,
)
from exchangelib.errors import (
    ErrorCannotOpenFileAttachment,
    ErrorFolderNotFound,
    ErrorInvalidPropertyRequest,
    ErrorIrresolvableConflict,
    ErrorMailboxMoveInProgress,
    ErrorMailboxStoreUnavailable,
    ErrorMimeContentConversionFailed,
    ErrorNameResolutionNoResults,
    RateLimitError,
    TransportError,
)
from exchangelib.items import Contact, Item, Message
from exchangelib.services import EWSService
from exchangelib.util import add_xml_child, create_element
from exchangelib.version import (
    EXCHANGE_2007,
    EXCHANGE_2010,
    EXCHANGE_2010_SP2,
    EXCHANGE_2013,
    EXCHANGE_2013_SP1,
    EXCHANGE_2016,
    EXCHANGE_2019,
)
from exchangelib.version import VERSIONS as EXC_VERSIONS
from future import utils as future_utils
from requests.exceptions import ConnectionError


# Exchange2 2019 patch - server dosen't connect with 2019 but with other versions creating an error mismatch (see CIAC-3086),
# overriding this function to remove minor version test and remove error throw.
# opened bug for exchanglib here https://github.com/ecederstrand/exchangelib/issues/1210
def our_fullname(self):  # pragma: no cover
    for build, api_version, full_name in EXC_VERSIONS:
        # removed 'or self.build.minor_version != build.minor_version'
        if self.build and self.build.major_version != build.major_version:
            continue
        if self.api_version == api_version:
            return full_name
    return None


Version.fullname = our_fullname

# Ignore warnings print to stdout
warnings.filterwarnings("ignore")

MNS, TNS = exchangelib.util.MNS, exchangelib.util.TNS

# consts
VERSIONS = {
    "2007": EXCHANGE_2007,
    "2010": EXCHANGE_2010,
    "2010_SP2": EXCHANGE_2010_SP2,
    "2013": EXCHANGE_2013,
    "2013_SP1": EXCHANGE_2013_SP1,
    "2016": EXCHANGE_2016,
    "2019": EXCHANGE_2019,
}

APP_NAME = "EWSv2"
ATTACHMENT_ORIGINAL_ITEM_ID = "originalItemId"
NEW_ITEM_ID = "newItemId"
MESSAGE_ID = "messageId"
ITEM_ID = "itemId"
MAILBOX = "mailbox"
MAILBOX_ID = "mailboxId"
FOLDER_ID = "id"

MOVED_TO_MAILBOX = "movedToMailbox"
MOVED_TO_FOLDER = "movedToFolder"

FILE_ATTACHMENT_TYPE = "FileAttachment"
ITEM_ATTACHMENT_TYPE = "ItemAttachment"
ATTACHMENT_TYPE = "attachmentType"

TOIS_PATH = "/root/Top of Information Store/"

ENTRY_CONTEXT = "EntryContext"
CONTEXT_UPDATE_EWS_ITEM = (
    f"EWS.Items(val.{ITEM_ID} == obj.{ITEM_ID} || "
    f"(val.{MESSAGE_ID} && obj.{MESSAGE_ID} && val.{MESSAGE_ID} == obj.{MESSAGE_ID}))"
)
CONTEXT_UPDATE_EWS_ITEM_FOR_ATTACHMENT = f"EWS.Items(val.{ITEM_ID} == obj.{ATTACHMENT_ORIGINAL_ITEM_ID})"
CONTEXT_UPDATE_FOLDER = f"EWS.Folders(val.{FOLDER_ID} == obj.{FOLDER_ID})"

LAST_RUN_TIME = "lastRunTime"
LAST_RUN_IDS = "ids"
LAST_RUN_FOLDER = "folderName"
ERROR_COUNTER = "errorCounter"

ITEMS_RESULTS_HEADERS = [
    "sender",
    "subject",
    "hasAttachments",
    "datetimeReceived",
    "receivedBy",
    "author",
    "toRecipients",
    "textBody",
]


LAST_RUN_IDS_QUEUE_SIZE = 500

# NOTE: Same method used in EWSMailSender
# If you are modifying this probably also need to modify in the other file


def exchangelib_cleanup():  # pragma: no cover
    try:
        exchangelib.close_connections()
    except Exception as ex:
        demisto.error(f"Error was found in exchangelib cleanup, ignoring: {ex}")


# Prep Functions
def parse_auth_type(auth_type: str):  # pragma: no cover
    auth_type = auth_type.lower()
    if auth_type == "ntlm":
        return NTLM
    elif auth_type == "basic":
        return BASIC
    elif auth_type == "digest":
        return DIGEST
    raise Exception("{} auth method is not supported. Choose one of {}".format(auth_type, "ntlm\\basic\\digest"))


# LOGGING
log_stream = None
log_handler = None


def start_logging():
    global log_stream
    global log_handler
    logging.raiseExceptions = False
    if log_stream is None:
        log_stream = StringIO()
        log_handler = logging.StreamHandler(stream=log_stream)
        log_handler.setFormatter(logging.Formatter(logging.BASIC_FORMAT))
        logger = logging.getLogger()
        logger.addHandler(log_handler)
        logger.setLevel(logging.DEBUG)


# Exchange 2010 Fixes
def fix_2010(client: EWSClient):  # pragma: no cover
    version = client.server_build if client.server_build else get_on_prem_build(client.version)
    if version <= EXCHANGE_2010_SP2:
        for m in (
            Item,
            Message,
            exchangelib.items.CalendarItem,
            exchangelib.items.Contact,
            exchangelib.items.DistributionList,
            exchangelib.items.PostItem,
            exchangelib.items.Task,
            exchangelib.items.MeetingRequest,
            exchangelib.items.MeetingResponse,
            exchangelib.items.MeetingCancellation,
        ):
            for i, f in enumerate(m.FIELDS):
                if f.name == "text_body":
                    m.FIELDS.pop(i)
                    break
        for m in (exchangelib.Folder, exchangelib.folders.Inbox):
            for i, f in enumerate(m.FIELDS):
                if f.name == "unread_count":
                    m.FIELDS.pop(i)
                    break

        def repr1(self):
            return self.__class__.__name__ + repr(
                (self.root, self.name, self.total_count, self.child_folder_count, self.folder_class, self.id, self.changekey)
            )

        def repr2(self):
            return self.__class__.__name__ + repr(
                (self.root, self.name, self.total_count, self.child_folder_count, self.folder_class, self.changekey)
            )

        def repr3(self):
            return self.__class__.__name__ + repr(
                (self.account, "[self]", self.name, self.total_count, self.child_folder_count, self.folder_class, self.changekey)
            )

        exchangelib.Folder.__repr__ = repr1
        exchangelib.folders.Inbox.__repr__ = exchangelib.folders.JunkEmail.__repr__ = repr2
        exchangelib.folders.Root.__repr__ = repr3

    start_logging()


def str_to_unicode(obj):  # pragma: no cover
    if isinstance(obj, dict):
        obj = {k: str_to_unicode(v) for k, v in list(obj.items())}
    elif isinstance(obj, list):
        obj = [str_to_unicode(k) for k in obj]
    elif isinstance(obj, str):
        obj = obj.encode("utf-8")
    return obj


def get_time_zone() -> EWSTimeZone | None:
    """get the XSOAR user time zone
    :return:
        returns an ``EWSTimeZone`` if TZ available or ``None`` if not
    :rtype: ``Optional[EWSTimeZone]``
    """
    time_zone = demisto.callingContext.get("context", {}).get("User", {}).get("timeZone", None)
    if time_zone:
        time_zone = EWSTimeZone(time_zone)
    return time_zone


def get_attachment_name(attachment_name, content_id="", is_inline=False, attachment_subject=""):  # pragma: no cover
    demisto.debug(
        f"get_attachment_name called with attachment_name='{attachment_name}', content_id='{content_id}', "
        f"is_inline={is_inline}, attachment_subject='{attachment_subject}'"
    )

    legacy_name = argToBoolean(demisto.params().get("legacy_name", False))

    if is_inline and content_id and content_id != "None" and not legacy_name:
        if attachment_name is None or attachment_name == "":
            return f"{content_id}-attachmentName-demisto_untitled_attachment"
        return f"{content_id}-attachmentName-{attachment_name}"
    if not attachment_name and attachment_subject:
        return attachment_subject
    if not attachment_name and not attachment_subject:
        return "demisto_untitled_attachment"
    return attachment_name


def send_email_to_mailbox(  # pragma: no cover
    account,
    to,
    subject,
    body,
    body_type,
    bcc,
    cc,
    reply_to,
    handle_inline_image: bool = True,
    html_body=None,
    attachments=None,
    raw_message=None,
    from_address=None,
):
    """
    Send an email to a mailbox.

    Args:
        body_type: type of the body. Can be 'html' or 'text' or None.
        account (Account): account from which to send an email.
        to (list[str]): a list of emails to send an email.
        subject (str): subject of the mail.
        body (str): body of the email.
        reply_to (list[str]): list of emails of which to reply to from the sent email.
        bcc (list[str]): list of email addresses for the 'bcc' field.
        cc (list[str]): list of email addresses for the 'cc' field.
        html_body (str): HTML formatted content (body) of the email to be sent. This argument
            overrides the "body" argument.
        attachments (list[str]): list of names of attachments to send.
        raw_message (str): Raw email message from MimeContent type.
        from_address (str): the email address from which to reply.
    """
    if not attachments:
        attachments = []
    message_body, inline_attachments = get_message_for_body_type(body, body_type, html_body, handle_inline_image)
    attachments += inline_attachments
    m = Message(
        account=account,
        mime_content=raw_message.encode("UTF-8") if raw_message else None,
        folder=account.sent,
        cc_recipients=cc,
        bcc_recipients=bcc,
        subject=subject,
        body=message_body,
        to_recipients=to,
        reply_to=reply_to,
        author=from_address,
    )
    if account.protocol.version.build <= EXCHANGE_2010_SP2:
        m.save()
        for attachment in attachments:
            m.attach(attachment)
        m.send()
    else:
        for attachment in attachments:
            m.attach(attachment)
        m.send_and_save()
    return m


def get_message_for_body_type(body, body_type, html_body, handle_inline_image: bool):
    """
    Compatibility with Data Collection - where body_type is not provided, we will use the html_body if it exists.
    Compatibility with 'send-mail' command - where body_type should be provided, we will use the body_type to decide.
    Args:
        body_type: type of the body. Can be 'html' or 'text' or None.
        body: plain text body.
        html_body: HTML formatted content (body) of the email to be sent.

    Returns:
        Body: the body of the message.
    """
    demisto.debug(f"get_message_for_body_type: Received {body_type=}, {handle_inline_image=}")
    attachments: list = []

    if html_body and handle_inline_image:
        html_body, attachments = handle_html(html_body)
        demisto.debug(f"get_message_for_body_type: Processed HTML body with {len(attachments)} attachments")

    if body_type is None:  # When called from a data collection task.
        return (HTMLBody(html_body) if html_body else Body(body)), attachments

    if body_type.lower() == "html" and html_body:  # When called from 'send-mail' command.
        return HTMLBody(html_body), attachments

    return Body(body) if (body or not html_body) else HTMLBody(html_body), attachments


class SearchMailboxes(EWSService):
    def __init__(self, protocol, limit):
        self.limit = limit
        super().__init__(protocol)

    SERVICE_NAME = "SearchMailboxes"
    element_container_name = f"{{{MNS}}}SearchMailboxesResult/{{{TNS}}}Items"

    @staticmethod
    def parse_element(element):  # pragma: no cover
        to_recipients = element.find(f"{{{TNS}}}ToRecipients")
        if to_recipients:
            to_recipients = [x.text if x is not None else None for x in to_recipients]

        result = {
            ITEM_ID: element.find(f"{{{TNS}}}Id").attrib["Id"] if element.find(f"{{{TNS}}}Id") is not None else None,
            MAILBOX: element.find(f"{{{TNS}}}Mailbox/{{{TNS}}}PrimarySmtpAddress").text
            if element.find(f"{{{TNS}}}Mailbox/{{{TNS}}}PrimarySmtpAddress") is not None
            else None,
            "subject": element.find(f"{{{TNS}}}Subject").text if element.find(f"{{{TNS}}}Subject") is not None else None,
            "toRecipients": to_recipients,
            "sender": element.find(f"{{{TNS}}}Sender").text if element.find(f"{{{TNS}}}Sender") is not None else None,
            "hasAttachments": element.find(f"{{{TNS}}}HasAttachment").text
            if element.find(f"{{{TNS}}}HasAttachment") is not None
            else None,
            "datetimeSent": element.find(f"{{{TNS}}}SentTime").text if element.find(f"{{{TNS}}}SentTime") is not None else None,
            "datetimeReceived": element.find(f"{{{TNS}}}ReceivedTime").text
            if element.find(f"{{{TNS}}}ReceivedTime") is not None
            else None,
        }

        return result

    def call(self, query, mailboxes):  # pragma: no cover
        if self.protocol.version.build < EXCHANGE_2013:
            raise NotImplementedError(f"{self.SERVICE_NAME} is only supported for Exchange 2013 servers and later")
        elements = list(self._get_elements(payload=self.get_payload(query, mailboxes)))
        return [self.parse_element(x) for x in elements]

    def get_payload(self, query, mailboxes):  # pragma: no cover
        def get_mailbox_search_scope(mailbox_id):
            mailbox_search_scope = create_element("t:MailboxSearchScope")
            add_xml_child(mailbox_search_scope, "t:Mailbox", mailbox_id)
            add_xml_child(mailbox_search_scope, "t:SearchScope", "All")
            return mailbox_search_scope

        mailbox_query_element = create_element("t:MailboxQuery")
        add_xml_child(mailbox_query_element, "t:Query", query)
        mailboxes_scopes = []
        for mailbox in mailboxes:
            mailboxes_scopes.append(get_mailbox_search_scope(mailbox))
        add_xml_child(mailbox_query_element, "t:MailboxSearchScopes", mailboxes_scopes)

        element = create_element(f"m:{self.SERVICE_NAME}")
        add_xml_child(element, "m:SearchQueries", mailbox_query_element)
        add_xml_child(element, "m:ResultType", "PreviewOnly")
        add_xml_child(element, "m:PageSize", str(self.limit))

        return element


def search_mailboxes(client: EWSClient, filter, limit=100, mailbox_search_scope=None, email_addresses=None):  # pragma: no cover
    """
    Search mailboxes for items matching the given filter.

    Args:
        client (EWSClient): The EWS client object.
        filter (str): The search filter to apply.
        limit (int): The maximum number of results to return. Default value is 100.
        mailbox_search_scope (str or list, optional): The mailbox search scope. Defaults to None.
        email_addresses (str, optional): Comma-separated list of email addresses to search. Defaults to None.

    Returns:
        dict: A dictionary containing the search results.

    Raises:
        Exception: If both mailbox_search_scope and email_addresses are provided, or if no searchable mailboxes are found.
    """
    mailbox_ids = []
    limit_argument = arg_to_number(limit)
    if not limit_argument:
        raise DemistoException(f"Invalid limit value: {limit}. Please provide a valid integer.")

    if mailbox_search_scope is not None and email_addresses is not None:
        raise Exception("Use one of the arguments - mailbox-search-scope or email-addresses, not both")
    if email_addresses:
        email_addresses = email_addresses.split(",")
        all_mailboxes = GetSearchableMailboxes(protocol=client.get_protocol()).call()
        for email_address in email_addresses:
            for mailbox in all_mailboxes:
                addr = mailbox.get(MAILBOX, None)
                if addr and email_address.lower() == addr.lower():
                    mailbox_ids.append(mailbox[MAILBOX_ID])
        if len(mailbox_ids) == 0:
            raise Exception("No searchable mailboxes were found for the provided email addresses.")
    elif mailbox_search_scope:
        mailbox_ids = mailbox_search_scope if type(mailbox_search_scope) is list else [mailbox_search_scope]
    else:
        all_mailboxes = GetSearchableMailboxes(protocol=client.get_protocol()).call()
        mailbox_ids = [x[MAILBOX_ID] for x in all_mailboxes if x.get(MAILBOX_ID, None)]
    try:
        search_results = SearchMailboxes(protocol=client.get_protocol(), limit=limit_argument).call(filter, mailbox_ids)
    except TransportError as e:
        if "ItemCount>0<" in str(e):
            return "No results for search query: " + filter
        else:
            raise e

    return get_entry_for_object("Search mailboxes results", CONTEXT_UPDATE_EWS_ITEM, search_results)


def get_last_run(client: EWSClient):
    last_run = demisto.getLastRun()
    if not last_run or last_run.get(LAST_RUN_FOLDER) != client.folder_name:
        last_run = {LAST_RUN_TIME: None, LAST_RUN_FOLDER: client.folder_name, LAST_RUN_IDS: []}
    if LAST_RUN_TIME in last_run and last_run[LAST_RUN_TIME] is not None:
        last_run[LAST_RUN_TIME] = EWSDateTime.from_string(last_run[LAST_RUN_TIME])

    # In case we have existing last_run data
    if last_run.get(LAST_RUN_IDS) is None:
        last_run[LAST_RUN_IDS] = []

    return last_run


def fetch_last_emails(
    client: EWSClient,
    folder_name="Inbox",
    since_datetime=None,
    exclude_ids=None,
    fetch_all_history=False,
    fetch_time="10 minutes",
):
    account = client.get_account(client.account_email)
    qs = client.get_folder_by_path(folder_name, account, is_public=client.is_public_folder)
    demisto.debug(f"since_datetime: {since_datetime}")
    if since_datetime:
        qs = qs.filter(datetime_received__gte=since_datetime)
    else:
        if not fetch_all_history:
            tz = EWSTimeZone("UTC")
            first_fetch_datetime = dateparser.parse(fetch_time)
            if not first_fetch_datetime:
                raise DemistoException("Failed to parse first last run time")
            first_fetch_ews_datetime = first_fetch_datetime.astimezone(tz)
            qs = qs.filter(datetime_received__gte=first_fetch_ews_datetime)
    qs = qs.filter().only(*[x.name for x in Message.FIELDS])
    qs = qs.filter().order_by("datetime_received")
    result = []
    exclude_ids = exclude_ids if exclude_ids else set()
    demisto.debug(f"Exclude ID list: {exclude_ids}")

    for item in qs:
        try:
            demisto.debug(
                f"Looking on subject={item.subject}, "
                f"message_id={item.message_id}, "
                f"created={item.datetime_created}, "
                f"received={item.datetime_received}"
            )
            if isinstance(item, Message) and item.message_id not in exclude_ids:
                result.append(item)
                demisto.debug(f"Appending {item.subject}, {item.message_id}.")
                if len(result) >= client.max_fetch:
                    break
        except ValueError as exc:
            future_utils.raise_from(
                ValueError("Got an error when pulling incidents. You might be using the wrong exchange version."), exc
            )
            raise exc
        except ErrorMimeContentConversionFailed as exc:
            demisto.debug(f"Encountered an ErrorMimeContentConversionFailed error object while iterating: {exc}.\
                Continuing to next item.")
            continue
        except AttributeError as exc:
            demisto.debug(f"Encountered an Attribute error object while iterating: {exc}.\
                 Continuing to next item.")

    demisto.debug(f"EWS V2 - Got total of {len(result)} from ews query. ")
    return result


def keys_to_camel_case(value):
    def str_to_camel_case(snake_str):
        # Add condition as Email object arrived in list and raised error
        if not isinstance(snake_str, str):
            return snake_str
        components = snake_str.split("_")
        return components[0] + "".join(x.title() for x in components[1:])

    if value is None:
        return None
    if isinstance(value, list | set):
        return [keys_to_camel_case(v) for v in value]
    if isinstance(value, dict):
        return {
            keys_to_camel_case(k): keys_to_camel_case(v) if isinstance(v, list | dict) else v for (k, v) in list(value.items())
        }

    return str_to_camel_case(value)


def email_ec(item):  # pragma: no cover
    return {
        "CC": None if not item.cc_recipients else [mailbox.email_address for mailbox in item.cc_recipients],
        "BCC": None if not item.bcc_recipients else [mailbox.email_address for mailbox in item.bcc_recipients],
        "To": None if not item.to_recipients else [mailbox.email_address for mailbox in item.to_recipients],
        "From": item.author.email_address,
        "Subject": item.subject,
        "Text": item.text_body,
        "HTML": item.body,
        "HeadersMap": {} if not item.headers else {header.name: header.value for header in item.headers},
    }


def parse_object_as_dict_with_serialized_items(object):
    raw_dict = {}
    if object is not None:
        for field in object.FIELDS:
            try:
                v = getattr(object, field.name, None)
                if v is not None:
                    json.dumps(v)
                    raw_dict[field.name] = v
            except (TypeError, OverflowError):
                demisto.debug(f"Data in field {field.name} is not serilizable, skipped field value is \n{v}\n")
                continue
    return raw_dict


def parse_item_as_dict(item, email_address=None, camel_case=False, compact_fields=False):  # pragma: no cover
    def parse_object_as_dict(object):
        raw_dict = {}
        if object is not None:
            for field in object.FIELDS:
                field_val = getattr(object, field.name, None)
                try:
                    json.dumps(field_val)
                except TypeError:
                    field_val = parse_object_as_dict(field_val)
                raw_dict[field.name] = field_val
        return raw_dict

    def parse_folder_as_json(folder):  # pragma: no cover
        raw_dict = parse_object_as_dict(folder)
        if "parent_folder_id" in raw_dict:
            raw_dict["parent_folder_id"] = parse_folder_as_json(raw_dict["parent_folder_id"])
        if "effective_rights" in raw_dict:
            raw_dict["effective_rights"] = parse_object_as_dict(raw_dict["effective_rights"])
        return raw_dict

    raw_dict = parse_object_as_dict_with_serialized_items(item)

    if getattr(item, "attachments", None):
        raw_dict["attachments"] = [parse_attachment_as_dict(item.id, x) for x in item.attachments]

    for time_field in ["datetime_sent", "datetime_created", "datetime_received", "last_modified_time", "reminder_due_by"]:
        value = getattr(item, time_field, None)
        if value:
            raw_dict[time_field] = value.ewsformat()

    for dict_field in [
        "effective_rights",
        "parent_folder_id",
        "conversation_id",
        "author",
        "extern_id",
        "received_by",
        "received_representing",
        "reply_to",
        "sender",
        "folder",
    ]:
        value = getattr(item, dict_field, None)
        if value:
            if type(value) is list:
                raw_dict[dict_field] = [parse_object_as_dict(x) for x in value]
            else:
                raw_dict[dict_field] = parse_object_as_dict(value)

    for list_dict_field in ["headers", "cc_recipients", "to_recipients"]:
        value = getattr(item, list_dict_field, None)
        if value:
            raw_dict[list_dict_field] = [parse_object_as_dict(x) for x in value]

    for list_str_field in ["categories"]:
        value = getattr(item, list_str_field, None)
        if value:
            raw_dict[list_str_field] = value

    if getattr(item, "folder", None):
        raw_dict["folder"] = parse_folder_as_json(item.folder)
        folder_path = (
            item.folder.absolute[len(TOIS_PATH) :] if item.folder.absolute.startswith(TOIS_PATH) else item.folder.absolute
        )
        raw_dict["folder_path"] = folder_path

    raw_dict["item_id"] = getattr(item, "id", None)
    raw_dict["id"] = getattr(item, "id", None)

    if compact_fields:
        new_dict = {}
        fields_list = [
            "datetime_created",
            "datetime_received",
            "datetime_sent",
            "sender",
            "has_attachments",
            "importance",
            "message_id",
            "last_modified_time",
            "size",
            "subject",
            "text_body",
            "headers",
            "body",
            "folder_path",
            "is_read",
            "categories",
        ]

        fields_list.append("item_id")

        for field in fields_list:
            if field in raw_dict:
                new_dict[field] = raw_dict.get(field)
        for field in ["received_by", "author", "sender"]:
            if field in raw_dict:
                new_dict[field] = raw_dict.get(field, {}).get("email_address")
        for field in ["to_recipients"]:
            if field in raw_dict:
                new_dict[field] = [x.get("email_address") for x in raw_dict[field]]
        attachments = raw_dict.get("attachments")
        if attachments and len(attachments) > 0:
            file_attachments = [x for x in attachments if x[ATTACHMENT_TYPE] == FILE_ATTACHMENT_TYPE]
            if len(file_attachments) > 0:
                new_dict["FileAttachments"] = file_attachments
            item_attachments = [x for x in attachments if x[ATTACHMENT_TYPE] == ITEM_ATTACHMENT_TYPE]
            if len(item_attachments) > 0:
                new_dict["ItemAttachments"] = item_attachments
        raw_dict = new_dict

    if camel_case:
        raw_dict = keys_to_camel_case(raw_dict)

    if email_address:
        raw_dict[MAILBOX] = email_address
    return raw_dict


def cast_mime_item_to_message(item):
    mime_content = item.mime_content
    email_policy = SMTP if mime_content.isascii() else SMTPUTF8
    if isinstance(mime_content, bytes):
        return email.message_from_bytes(mime_content, policy=email_policy)  # type: ignore[arg-type]
    else:
        return email.message_from_string(mime_content, policy=email_policy)  # type: ignore[arg-type]


def parse_incident_from_item(item, is_fetch, mark_as_read):  # pragma: no cover
    incident = {}
    labels = []

    try:
        try:
            incident["details"] = item.text_body or item.body
        except AttributeError:
            incident["details"] = item.body

        incident["name"] = item.subject
        labels.append({"type": "Email/subject", "value": item.subject})
        incident["occurred"] = item.datetime_created.ewsformat()

        # handle recipients
        if item.to_recipients:
            for recipient in item.to_recipients:
                labels.append({"type": "Email", "value": recipient.email_address})

        # handle cc
        if item.cc_recipients:
            for recipient in item.cc_recipients:
                labels.append({"type": "Email/cc", "value": recipient.email_address})
        # handle email from
        if item.sender:
            labels.append({"type": "Email/from", "value": item.sender.email_address})

        # email format
        email_format = ""
        try:
            if item.text_body:
                labels.append({"type": "Email/text", "value": item.text_body})
                email_format = "text"
        except AttributeError:
            pass
        if item.body:
            labels.append({"type": "Email/html", "value": item.body})
            email_format = "HTML"
        labels.append({"type": "Email/format", "value": email_format})

        # handle attachments
        if item.attachments:
            incident["attachment"] = []
            for attachment in item.attachments:
                if attachment is not None:
                    attachment.parent_item = item
                    file_result = None
                    label_attachment_type = None
                    label_attachment_id_type = None
                    if isinstance(attachment, FileAttachment):
                        try:
                            if attachment.content:
                                # file attachment
                                label_attachment_type = "attachments"
                                label_attachment_id_type = "attachmentId"

                                # save the attachment
                                file_name = get_attachment_name(
                                    attachment_name=attachment.name,
                                    content_id=attachment.content_id,
                                    is_inline=attachment.is_inline,
                                )
                                file_result = fileResult(file_name, attachment.content)

                                # check for error
                                if file_result["Type"] == entryTypes["error"]:
                                    demisto.error(file_result["Contents"])
                                    raise Exception(file_result["Contents"])

                                # save attachment to incident
                                incident["attachment"].append(
                                    {
                                        "path": file_result["FileID"],
                                        "name": get_attachment_name(
                                            attachment_name=attachment.name,
                                            content_id=attachment.content_id,
                                            is_inline=attachment.is_inline,
                                        ),
                                        "description": FileAttachmentType.ATTACHED if not attachment.is_inline else "",
                                    }
                                )
                        except TypeError as e:
                            if str(e) != "must be string or buffer, not None":
                                raise
                            continue
                        except ErrorCannotOpenFileAttachment as e:
                            if str(e) != "The attachment could not be opened.":
                                raise
                            demisto.error(f"Skipped attachment: {attachment.name} - {e}")
                            continue
                    else:
                        # other item attachment
                        label_attachment_type = "attachmentItems"
                        label_attachment_id_type = "attachmentItemsId"
                        formatted_message: str | bytes
                        # save the attachment
                        if hasattr(attachment, "item") and attachment.item.mime_content:
                            # Some items arrive with bytes attachemnt
                            attached_email = cast_mime_item_to_message(attachment.item)
                            if attachment.item.headers:
                                attached_email_headers = []
                                for h, v in list(attached_email.items()):
                                    if not isinstance(v, str):
                                        try:
                                            v = str(v)
                                        except:  # noqa: E722
                                            demisto.debug(f'cannot parse the header "{h}"')
                                            continue

                                    v = " ".join(map(str.strip, v.split("\r\n")))
                                    attached_email_headers.append((h.lower(), v))

                                for header in attachment.item.headers:
                                    if (
                                        header.name.lower(),
                                        header.value,
                                    ) not in attached_email_headers and header.name.lower() != "content-type":
                                        try:
                                            attached_email.add_header(header.name, header.value)
                                        except ValueError as err:
                                            if "There may be at most" not in str(err):
                                                raise err
                            formatted_message = get_formatted_message(attached_email)
                            file_result = fileResult(
                                get_attachment_name(
                                    attachment_name=attachment.name,
                                    content_id=attachment.content_id,
                                    is_inline=attachment.is_inline,
                                    attachment_subject=attachment.item.subject,
                                )
                                + ".eml",
                                formatted_message,
                            )

                        if file_result:
                            # check for error
                            if file_result["Type"] == entryTypes["error"]:
                                demisto.error(file_result["Contents"])
                                raise Exception(file_result["Contents"])

                            # save attachment to incident
                            incident["attachment"].append(
                                {
                                    "path": file_result["FileID"],
                                    "name": get_attachment_name(
                                        attachment_name=attachment.name,
                                        content_id=attachment.content_id,
                                        is_inline=attachment.is_inline,
                                        attachment_subject=attachment.item.subject,
                                    )
                                    + ".eml",
                                }
                            )

                        else:
                            incident["attachment"].append(
                                {
                                    "name": get_attachment_name(
                                        attachment_name=attachment.name,
                                        content_id=attachment.content_id,
                                        is_inline=attachment.is_inline,
                                        attachment_subject=attachment.item.subject,
                                    )
                                    + ".eml",
                                }
                            )

                    labels.append(
                        {
                            "type": label_attachment_type,
                            "value": get_attachment_name(
                                attachment_name=attachment.name,
                                content_id=attachment.content_id,
                                is_inline=attachment.is_inline,
                                attachment_subject="" if isinstance(attachment, FileAttachment) else attachment.item.subject,
                            ),
                        }
                    )

                    labels.append({"type": label_attachment_id_type, "value": attachment.attachment_id.id})

        # handle headers
        if item.headers:
            headers = []
            for header in item.headers:
                labels.append({"type": f"Email/Header/{header.name}", "value": str(header.value)})
                headers.append(f"{header.name}: {header.value}")
            labels.append({"type": "Email/headers", "value": "\r\n".join(headers)})

        # handle item id
        if item.message_id:
            labels.append({"type": "Email/MessageId", "value": str(item.message_id)})
            # fetch history
            incident["dbotMirrorId"] = str(item.message_id)

        if item.id:
            labels.append({"type": "Email/ID", "value": item.id})
            labels.append({"type": "Email/itemId", "value": item.id})

        # handle conversion id
        if item.conversation_id:
            labels.append({"type": "Email/ConversionID", "value": item.conversation_id.id})

        if mark_as_read and is_fetch:
            item.is_read = True
            try:
                item.save()
            except ErrorIrresolvableConflict:
                time.sleep(0.5)
                item.save()
            except ValueError as e:
                if item.subject and len(item.subject) > 255:
                    demisto.debug(
                        "Length of message subject is greater than 255, item.save could not handle it, cutting the subject."
                    )
                    sub_subject = f"Length of subject greater than 255 characters. Partial subject: {item.subject[:180]}"
                    item.subject = sub_subject
                    item.save()
                else:
                    raise e

        incident["labels"] = labels
        incident["rawJSON"] = json.dumps(parse_item_as_dict(item, None), ensure_ascii=False)

    except Exception as e:
        if "Message is not decoded yet" in str(e):
            demisto.debug("EWS v2 - Skipped a protected message")
            return None
        else:
            raise e

    return incident


def get_formatted_message(attached_email) -> str | bytes:
    try:
        return attached_email.as_string()
    except UnicodeEncodeError:
        return attached_email.as_bytes()
    except Exception as e:
        demisto.info(f"Could not parse attached mail as message, {e}")
        return " Could not format message"


def fetch_emails_as_incidents(
    client: EWSClient, skip_unparsable_emails: bool = False, fetch_all_history=False, fetch_time="10 minutes"
) -> list[dict]:
    last_run = get_last_run(client)
    excluded_ids = set(last_run.get(LAST_RUN_IDS, []))

    try:
        last_emails = fetch_last_emails(
            client, client.folder_name, last_run.get(LAST_RUN_TIME), excluded_ids, fetch_all_history, fetch_time
        )

        incidents = []
        incident = {}  # type: Dict[Any, Any]
        current_fetch_ids = set()
        last_incident_run_time = None

        for item in last_emails:
            try:
                if item.message_id:
                    current_fetch_ids.add(item.message_id)
                    incident = parse_incident_from_item(item, True, client.mark_as_read)
                    demisto.debug(f"Parsed incident: {item.message_id}")
                    if incident:
                        incidents.append(incident)
                        last_incident_run_time = item.datetime_received
                        demisto.debug(f"Appended incident: {item.message_id}")

                    if len(incidents) >= client.max_fetch:
                        break
            except Exception as e:
                if not skip_unparsable_emails:  # default is to raise and exception and fail the command
                    raise

                # when the skip param is `True`, we log the exceptions and move on instead of failing the whole fetch
                error_msg = (
                    "Encountered email parsing issue while fetching. "
                    f"Skipping item with message id: {item.message_id or '<error parsing message_id>'}"
                )
                demisto.debug(f"{error_msg}, Error: {e!s} {traceback.format_exc()}")
                demisto.updateModuleHealth(error_msg, is_error=False)

        demisto.debug(f"EWS V2 - ending fetch - got {len(incidents)} incidents.")
        last_fetch_time = last_run.get(LAST_RUN_TIME)
        last_incident_run_time = last_incident_run_time if last_incident_run_time else last_fetch_time

        # making sure both last fetch time and the time of last incident are the same type for comparing.
        if isinstance(last_incident_run_time, EWSDateTime):
            last_incident_run_time = last_incident_run_time.ewsformat()

        if isinstance(last_fetch_time, EWSDateTime):
            last_fetch_time = last_fetch_time.ewsformat()

        debug_msg = "#### last_incident_time: {}({}). last_fetch_time: {}({}) ####"
        demisto.debug(
            debug_msg.format(last_incident_run_time, type(last_incident_run_time), last_fetch_time, type(last_fetch_time))
        )

        # If the fetch query is not fully fetched (we didn't have any time progress) - then we keep the
        # id's from current fetch until progress is made. This is for when max_fetch < incidents_from_query.
        if not last_incident_run_time or not last_fetch_time or last_incident_run_time > last_fetch_time:
            ids = current_fetch_ids
        else:
            ids = current_fetch_ids | excluded_ids
        new_last_run = {
            LAST_RUN_TIME: last_incident_run_time,
            LAST_RUN_FOLDER: client.folder_name,
            LAST_RUN_IDS: list(ids),
            ERROR_COUNTER: 0,
        }

        demisto.setLastRun(new_last_run)
        return incidents

    except RateLimitError:
        if LAST_RUN_TIME in last_run:
            last_run[LAST_RUN_TIME] = last_run[LAST_RUN_TIME].ewsformat()
        if ERROR_COUNTER not in last_run:
            last_run[ERROR_COUNTER] = 0
        last_run[ERROR_COUNTER] += 1
        demisto.setLastRun(last_run)
        if last_run[ERROR_COUNTER] > 2:
            raise
        return []


def get_entry_for_file_attachment(item_id, attachment):  # pragma: no cover
    entry = fileResult(
        get_attachment_name(attachment_name=attachment.name, content_id=attachment.content_id, is_inline=attachment.is_inline),
        attachment.content,
    )
    ec = {CONTEXT_UPDATE_EWS_ITEM_FOR_ATTACHMENT + CONTEXT_UPDATE_FILE_ATTACHMENT: parse_attachment_as_dict(item_id, attachment)}
    entry[ENTRY_CONTEXT] = filter_dict_null(ec)
    return entry


def parse_attachment_as_dict(item_id, attachment):  # pragma: no cover
    try:
        # if this is a file attachment or a non-empty email attachment
        if isinstance(attachment, FileAttachment) or hasattr(attachment, "item"):
            attachment_content = attachment.content if isinstance(attachment, FileAttachment) else attachment.item.mime_content

            return {
                ATTACHMENT_ORIGINAL_ITEM_ID: item_id,
                ATTACHMENT_ID: attachment.attachment_id.id,
                "attachmentName": get_attachment_name(
                    attachment_name=attachment.name,
                    content_id=attachment.content_id,
                    is_inline=attachment.is_inline,
                    attachment_subject="" if isinstance(attachment, FileAttachment) else attachment.item.subject,
                ),
                "attachmentSHA256": hashlib.sha256(attachment_content).hexdigest() if attachment_content else None,
                "attachmentContentType": attachment.content_type,
                "attachmentContentId": attachment.content_id,
                "attachmentContentLocation": attachment.content_location,
                "attachmentSize": attachment.size,
                "attachmentLastModifiedTime": attachment.last_modified_time.ewsformat(),
                "attachmentIsInline": attachment.is_inline,
                ATTACHMENT_TYPE: FILE_ATTACHMENT_TYPE if isinstance(attachment, FileAttachment) else ITEM_ATTACHMENT_TYPE,
            }

        # If this is an empty email attachment
        else:
            return {
                ATTACHMENT_ORIGINAL_ITEM_ID: item_id,
                ATTACHMENT_ID: attachment.attachment_id.id,
                "attachmentName": get_attachment_name(
                    attachment_name=attachment.name,
                    content_id=attachment.content_id,
                    is_inline=attachment.is_inline,
                    attachment_subject="" if isinstance(attachment, FileAttachment) else attachment.item.subject,
                ),
                "attachmentSize": attachment.size,
                "attachmentLastModifiedTime": attachment.last_modified_time.ewsformat(),
                "attachmentIsInline": attachment.is_inline,
                ATTACHMENT_TYPE: FILE_ATTACHMENT_TYPE if isinstance(attachment, FileAttachment) else ITEM_ATTACHMENT_TYPE,
            }

    except (TypeError, ErrorCannotOpenFileAttachment) as e:
        if str(e) not in ("must be string or buffer, not None", "The attachment could not be opened."):
            raise
        demisto.debug(f"Add attachment info to context, without the content. Error: {e!s}")
        return {
            ATTACHMENT_ORIGINAL_ITEM_ID: item_id,
            ATTACHMENT_ID: attachment.attachment_id.id,
            "attachmentName": get_attachment_name(
                attachment_name=attachment.name,
                content_id=attachment.content_id,
                is_inline=attachment.is_inline,
                attachment_subject="" if isinstance(attachment, FileAttachment) else attachment.item.subject,
            ),
            "attachmentSHA256": None,
            "attachmentContentType": attachment.content_type,
            "attachmentContentId": attachment.content_id,
            "attachmentContentLocation": attachment.content_location,
            "attachmentSize": attachment.size,
            "attachmentLastModifiedTime": attachment.last_modified_time.ewsformat(),
            "attachmentIsInline": attachment.is_inline,
            ATTACHMENT_TYPE: FILE_ATTACHMENT_TYPE if isinstance(attachment, FileAttachment) else ITEM_ATTACHMENT_TYPE,
        }


def get_entry_for_item_attachment(item_id, attachment, target_email):  # pragma: no cover
    item = attachment.item
    dict_result = parse_attachment_as_dict(item_id, attachment)
    dict_result.update(parse_item_as_dict(item, target_email, camel_case=True, compact_fields=True))
    title = f'EWS get attachment got item for "{target_email}", "{get_attachment_name(attachment_name=attachment.name, content_id=attachment.content_id, is_inline=attachment.is_inline, attachment_subject=attachment.item.subject)}"'  # noqa: E501

    return get_entry_for_object(title, CONTEXT_UPDATE_EWS_ITEM_FOR_ATTACHMENT + CONTEXT_UPDATE_ITEM_ATTACHMENT, dict_result)


def fetch_attachments_for_message(
    client: EWSClient, item_id: str, target_mailbox: Optional[str] = None, attachment_ids=[], identifiers_filter=""
) -> list:  # pragma: no cover
    identifiers_filter = argToList(identifiers_filter)
    account = client.get_account(target_mailbox or client.account_email)
    attachment_ids = argToList(attachment_ids)
    attachments = client.get_attachments_for_item(item_id, account, attachment_ids)
    entries = []
    for attachment in attachments:
        if isinstance(attachment, FileAttachment):
            try:
                if attachment.content:
                    entries.append(get_entry_for_file_attachment(item_id, attachment))
            except (TypeError, ErrorCannotOpenFileAttachment) as e:
                if str(e) not in ("must be string or buffer, not None", "The attachment could not be opened."):
                    raise
                demisto.debug(f"Skipping attachment '{attachment.name}', Error: {e}")
        else:
            entries.append(get_entry_for_item_attachment(item_id, attachment, account.primary_smtp_address))
            if attachment.item.mime_content:
                attached_email = cast_mime_item_to_message(attachment.item)
                entries.append(
                    fileResult(
                        get_attachment_name(
                            attachment.name,
                            content_id=attachment.content_id,
                            is_inline=attachment.is_inline,
                            attachment_subject=attachment.item.subject,
                        )
                        + ".eml",
                        get_formatted_message(attached_email),
                    )
                )

    return entries


def prepare_args(d):  # pragma: no cover
    d = {k.replace("-", "_"): v for k, v in list(d.items())}
    if "is_public" in d:
        d["is_public"] = d["is_public"] == "True"
    return d


def get_limited_number_of_messages_from_qs(qs, limit):  # pragma: no cover
    count = 0
    results = []
    for item in qs:
        if count == limit:
            break
        if isinstance(item, Message):
            count += 1
            results.append(item)
    return results


def search_items_in_mailbox(
    client: EWSClient,
    query=None,
    message_id=None,
    folder_path="",
    limit=100,
    target_mailbox=None,
    is_public=None,
    selected_fields="all",
    surround_id_with_angle_brackets=True,
):  # pragma: no cover
    if not query and not message_id:
        return_error("Missing required argument. Provide query or message-id")
    if argToBoolean(surround_id_with_angle_brackets) and message_id and message_id[0] != "<" and message_id[-1] != ">":
        message_id = f"<{message_id}>"
    account = client.get_account(target_mailbox or client.account_email)
    limit = int(limit)
    if folder_path.lower() == "inbox":
        folders = [account.inbox]
    elif folder_path:
        is_public = client.is_default_folder(folder_path, is_public)
        folders = [client.get_folder_by_path(folder_path, account, is_public)]
    else:
        folders = FolderCollection(account=account, folders=[account.root.tois]).find_folders()  # pylint: disable=E1101
    items = []  # type: ignore
    selected_all_fields = selected_fields == "all"
    if selected_all_fields:
        restricted_fields = {x.name for x in Message.FIELDS}  # type: ignore
    else:
        restricted_fields = set(argToList(selected_fields))  # type: ignore
        restricted_fields.update(["id", "message_id"])  # type: ignore

    for folder in folders:
        if Message not in folder.supported_item_models:
            continue
        if query:
            items_qs = folder.filter(query).only(*restricted_fields)
        else:
            items_qs = folder.filter(message_id=message_id).only(*restricted_fields)
        items += get_limited_number_of_messages_from_qs(items_qs, limit)
        if len(items) >= limit:
            break
    items = items[:limit]
    searched_items_result = [
        parse_item_as_dict(item, account.primary_smtp_address, camel_case=True, compact_fields=selected_all_fields)
        for item in items
    ]
    if not selected_all_fields:
        # we show id as 'itemId' for BC
        restricted_fields.remove("id")
        restricted_fields.add("itemId")
        searched_items_result = [
            {k: v for (k, v) in i.items() if k in keys_to_camel_case(restricted_fields)} for i in searched_items_result
        ]
    return get_entry_for_object(
        "Searched items",
        CONTEXT_UPDATE_EWS_ITEM,
        searched_items_result,
        headers=ITEMS_RESULTS_HEADERS if selected_all_fields else None,
    )


def parse_physical_address(address):
    result = {}
    for attr in ["city", "country", "label", "state", "street", "zipcode"]:
        result[attr] = getattr(address, attr, None)
    return result


def parse_phone_number(phone_number):
    result = {attr: getattr(phone_number, attr, None) for attr in ["label", "phone_number"]}
    return result if result.get("phone_number") else {}


def is_jsonable(x):
    try:
        json.dumps(x)
        return True
    except Exception:
        return False


def parse_contact(contact):
    contact_dict = parse_object_as_dict_with_serialized_items(contact)
    for k in contact_dict:
        v = contact_dict[k]
        if isinstance(v, EWSDateTime):
            contact_dict[k] = v.ewsformat()  # pylint: disable=E4702

    contact_dict["id"] = contact.id
    if isinstance(contact, Contact) and contact.physical_addresses:
        contact_dict["physical_addresses"] = list(map(parse_physical_address, contact.physical_addresses))
    if isinstance(contact, Contact) and contact.phone_numbers:
        contact_dict["phone_numbers"] = [elt for elt in map(parse_phone_number, contact.phone_numbers) if elt]
    if isinstance(contact, Contact) and contact.email_addresses and len(contact.email_addresses) > 0:
        contact_dict["emailAddresses"] = [x.email for x in contact.email_addresses]
    contact_dict = keys_to_camel_case(contact_dict)
    contact_dict = {k: v for k, v in contact_dict.items() if (v and is_jsonable(v))}
    return contact_dict


def get_contacts(client: EWSClient, limit, target_mailbox=None):  # pragma: no cover
    account = client.get_account(target_mailbox or client.account_email)
    contacts = []

    for contact in account.contacts.all()[: int(limit)]:  # pylint: disable=E1101
        contact = parse_contact(contact)
        contact["originMailbox"] = target_mailbox
        contacts.append(contact)
    return get_entry_for_object(
        f"Email contacts for {target_mailbox or client.account_email}",
        "Account.Email(val.Address == obj.originMailbox).EwsContacts",
        contacts,
    )


def find_folders(client: EWSClient, target_mailbox=None, is_public=None):  # pragma: no cover
    account = client.get_account(target_mailbox or client.account_email)
    root = account.public_folders_root if is_public else account.root.tois  # pylint: disable=E1101
    root_collection = FolderCollection(account=account, folders=[root])
    folders = []
    for f in root_collection.find_folders():  # pylint: disable=E1101
        folder = folder_to_context_entry(f)
        folders.append(folder)

    readable_output = root.tree()  # pylint: disable=E1101

    return {
        "Type": entryTypes["note"],
        "Contents": folders,
        "ContentsFormat": formats["json"],
        "ReadableContentsFormat": formats["markdown"],
        "HumanReadable": readable_output,
        ENTRY_CONTEXT: {"EWS.Folders(val.id == obj.id)": folders},
    }


def get_items_from_folder(
    client: EWSClient, folder_path, limit=100, target_mailbox=None, is_public=None, get_internal_item="no"
):  # pragma: no cover
    account = client.get_account(target_mailbox or client.account_email)
    limit = int(limit)
    get_internal_item = get_internal_item == "yes"
    is_public = client.is_default_folder(folder_path, is_public)
    folder = client.get_folder_by_path(folder_path, account, is_public)
    qs = folder.filter().order_by("-datetime_created")[:limit]
    items = get_limited_number_of_messages_from_qs(qs, limit)
    items_result = []

    for item in items:
        item_attachment = parse_item_as_dict(item, account.primary_smtp_address, camel_case=True, compact_fields=True)

        for attachment in item.attachments:
            if attachment is not None:
                attachment.parent_item = item
                if get_internal_item and isinstance(attachment, ItemAttachment) and isinstance(attachment.item, Message):
                    # if found item attachment - switch item to the attchment
                    item_attachment = parse_item_as_dict(
                        attachment.item, account.primary_smtp_address, camel_case=True, compact_fields=True
                    )
                    break

        items_result.append(item_attachment)
    hm_headers = ["sender", "subject", "hasAttachments", "datetimeReceived", "receivedBy", "author", "toRecipients", "itemId"]
    return get_entry_for_object("Items in folder " + folder_path, CONTEXT_UPDATE_EWS_ITEM, items_result, headers=hm_headers)


def get_items(client: EWSClient, item_ids, target_mailbox=None):  # pragma: no cover
    account = client.get_account(target_mailbox or client.account_email)
    item_ids = argToList(item_ids)

    items = client.get_items_from_mailbox(account, item_ids)
    items = [x for x in items if isinstance(x, Message)]
    items_as_incidents = [parse_incident_from_item(x, False, client.mark_as_read) for x in items]
    items_to_context = [parse_item_as_dict(x, account.primary_smtp_address, True, True) for x in items]

    return {
        "Type": entryTypes["note"],
        "Contents": items_as_incidents,
        "ContentsFormat": formats["json"],
        "ReadableContentsFormat": formats["markdown"],
        "HumanReadable": tableToMarkdown("Get items", items_to_context, ITEMS_RESULTS_HEADERS),
        ENTRY_CONTEXT: {
            CONTEXT_UPDATE_EWS_ITEM: items_to_context,
            "Email": [email_ec(item) for item in items],
        },
    }


def get_autodiscovery_config():  # pragma: no cover
    config_dict = demisto.getIntegrationContext()
    return {
        "Type": entryTypes["note"],
        "Contents": config_dict,
        "ContentsFormat": formats["json"],
        "ReadableContentsFormat": formats["markdown"],
        "HumanReadable": tableToMarkdown("Auto-Discovery Exchange Configuration", config_dict),
    }


def format_identifier(identifier):
    """
    Exchangelib has a default smtp routing type. If there's no given routingtype, add explicitly so that
    exchangelib can be searched by secondary email addresses without making cusomter add it manually
    """
    return f"smtp:{identifier}" if "@" in identifier and ":" not in identifier else identifier


def resolve_name_command(client: EWSClient, args):  # pragma: no cover
    protocol = client.get_protocol()
    unresolved_entry = format_identifier(args["identifier"])
    full_contact_data = argToBoolean(args.get("full_contact_data", True))
    resolved_names = protocol.resolve_names([unresolved_entry], return_full_contact_data=full_contact_data, search_scope="")
    demisto.debug(f"{len(resolved_names)=}")

    output = []
    for rn in resolved_names:
        if isinstance(rn, ErrorNameResolutionNoResults):
            demisto.info(f"got ErrorNameResolutionNoResults error, {rn!s}")
            return "No results were found."
        elif isinstance(rn, tuple):
            mail, contact = rn
        else:
            mail, contact = rn, None
        mail_context = parse_item_as_dict(mail)
        if contact:
            mail_context["FullContactInfo"] = parse_contact(contact)
        output.append(mail_context)
    return get_entry_for_object(
        "Resolved Names",
        "EWS.ResolvedNames(val.email_address && val.email_address == obj.email_address)",
        remove_empty_elements(output),  # noqa: F405
        headers=["primary_email_address", "name", "mailbox_type", "routing_type"],
        hr_header_changes={"email_address": "primary_email_address"},
    )


def get_item_as_eml(client: EWSClient, item_id, target_mailbox=None):  # pragma: no cover
    account = client.get_account(target_mailbox or client.account_email)
    item = client.get_item_from_mailbox(account, item_id)

    if item.mime_content:
        # came across an item with bytes attachemnt which failed in the source code, added this to keep functionality
        email_content = cast_mime_item_to_message(item)
        if item.headers:
            attached_email_headers = []
            for h, v in list(email_content.items()):
                if not isinstance(v, str):
                    try:
                        v = str(v)
                    except:  # noqa: E722
                        demisto.debug(f'cannot parse the header "{h}"')

                v = " ".join(map(str.strip, v.split("\r\n")))
                attached_email_headers.append((h.lower(), v))
            for header in item.headers:
                if (header.name.lower(), header.value) not in attached_email_headers and header.name.lower() != "content-type":
                    try:
                        email_content.add_header(header.name, header.value)
                    except ValueError as err:
                        if "There may be at most" not in str(err):
                            raise err
        eml_name = item.subject if item.subject else "demisto_untitled_eml"
        file_result = fileResult(eml_name + ".eml", get_formatted_message(email_content))
        file_result = file_result if file_result else "Failed uploading eml file to war room"

        return file_result
    return None


def collect_manual_attachments(manual_attach_obj):  # pragma: no cover
    attachments = []
    for attachment in manual_attach_obj:
        res = demisto.getFilePath(os.path.basename(attachment["RealFileName"]))

        file_path = res["path"]
        with open(file_path, "rb") as f:
            attachments.append(FileAttachment(content=f.read(), name=attachment["FileName"]))

    return attachments


def process_attachments(attach_cids="", attach_ids="", attach_names="", manual_attach_obj=None):  # pragma: no cover
    if manual_attach_obj is None:
        manual_attach_obj = []
    file_entries_for_attachments = []  # type: list
    attachments_names = []  # type: list

    if attach_ids:
        file_entries_for_attachments = attach_ids if isinstance(attach_ids, list) else attach_ids.split(",")
        if attach_names:
            attachments_names = attach_names if isinstance(attach_names, list) else attach_names.split(",")
        else:
            for att_id in file_entries_for_attachments:
                att_name = demisto.getFilePath(att_id)["name"]
                if isinstance(att_name, list):
                    att_name = att_name[0]
                attachments_names.append(att_name)
        if len(file_entries_for_attachments) != len(attachments_names):
            raise Exception("attachIDs and attachNames lists should be the same length")

    attachments = collect_manual_attachments(manual_attach_obj)

    if attach_cids:
        file_entries_for_attachments_inline = attach_cids if isinstance(attach_cids, list) else attach_cids.split(",")
        for att_id_inline in file_entries_for_attachments_inline:
            try:
                file_info = demisto.getFilePath(att_id_inline)
            except Exception as ex:
                demisto.info(f"EWS error from getFilePath: {ex}")
                raise Exception(f"entry {att_id_inline} does not contain a file")
            att_name_inline = file_info["name"]
            with open(file_info["path"], "rb") as f:
                attachments.append(
                    FileAttachment(content=f.read(), name=att_name_inline, is_inline=True, content_id=att_name_inline)
                )

    for i in range(len(file_entries_for_attachments)):
        entry_id = file_entries_for_attachments[i]
        attachment_name = attachments_names[i]
        try:
            res = demisto.getFilePath(entry_id)
        except Exception as ex:
            raise Exception(f"entry {entry_id} does not contain a file: {ex!s}")
        file_path = res["path"]
        with open(file_path, "rb") as f:
            attachments.append(FileAttachment(content=f.read(), name=attachment_name))
    return attachments, attachments_names


def get_none_empty_addresses(addresses_ls):
    return [adress for adress in addresses_ls if adress]


def send_email(client: EWSClient, args):
    time_zone = get_time_zone()
    account = client.get_account(target_mailbox=client.account_email, time_zone=time_zone)
    bcc = get_none_empty_addresses(argToList(args.get("bcc")))
    cc = get_none_empty_addresses(argToList(args.get("cc")))
    to = get_none_empty_addresses(argToList(args.get("to")))
    replyTo = get_none_empty_addresses(argToList(args.get("replyTo")))
    render_body = argToBoolean(args.get("renderBody") or False)
    handle_inline_image: bool = argToBoolean(args.get("handle_inline_image", True))
    subject = args.get("subject")
    subject = subject[:252] + "..." if len(subject) > 255 else subject

    attachments, attachments_names = process_attachments(
        args.get("attachCIDs", ""), args.get("attachIDs", ""), args.get("attachNames", ""), args.get("manualAttachObj") or []
    )

    body_type = args.get("bodyType", args.get("body_type"))
    send_email_to_mailbox(
        account=account,
        to=to,
        subject=subject,
        body=args.get("body"),
        body_type=body_type,
        bcc=bcc,
        cc=cc,
        reply_to=replyTo,
        handle_inline_image=handle_inline_image,
        html_body=args.get("htmlBody"),
        attachments=attachments,
        raw_message=args.get("raw_message"),
        from_address=args.get("from"),
    )
    result_object = {
        "from": args.get("from") or account.primary_smtp_address,
        "to": to,
        "subject": subject,
        "attachments": attachments_names,
    }

    results = [
        {
            "Type": entryTypes["note"],
            "Contents": result_object,
            "ContentsFormat": formats["json"],
            "ReadableContentsFormat": formats["markdown"],
            "HumanReadable": tableToMarkdown("Sent email", result_object),
        }
    ]
    if render_body:
        results.append({"Type": entryTypes["note"], "ContentsFormat": formats["html"], "Contents": args.get("htmlBody")})
    return results


def reply_email(client: EWSClient, args: dict):  # pragma: no cover
    time_zone = get_time_zone()
    account = client.get_account(target_mailbox=client.account_email, time_zone=time_zone)
    bcc = argToList(args.get("bcc"))
    cc = argToList(args.get("cc"))
    to = argToList(args.get("to"))
    handle_inline_image: bool = argToBoolean(args.get("handle_inline_image", True))
    from_mailbox = args.get("from")
    subject = args.get("subject", "")
    subject = subject[:252] + "..." if subject and len(subject) > 255 else subject

    attachments, attachments_names = process_attachments(
        args.get("attachCIDs", ""), args.get("attachIDs", ""), args.get("attachNames", ""), args.get("manualAttachObj") or []
    )

    client.reply_email(
        in_reply_to=args.get("inReplyTo", ""),
        to=to,
        body=args.get("body", ""),
        subject=subject,
        bcc=bcc,
        cc=cc,
        html_body=args.get("htmlBody"),
        attachments=attachments,
        from_mailbox=from_mailbox,
        account=account,
        handle_inline_image=handle_inline_image,
    )
    result_object = {
        "from": from_mailbox or account.primary_smtp_address,
        "to": to,
        "subject": subject,
        "attachments": attachments_names,
    }

    return {
        "Type": entryTypes["note"],
        "Contents": result_object,
        "ContentsFormat": formats["json"],
        "ReadableContentsFormat": formats["markdown"],
        "HumanReadable": tableToMarkdown("Sent email", result_object),
    }


def test_module(client: EWSClient):  # pragma: no cover
    try:
        account = client.get_account(client.account_email)
        folder = client.get_folder_by_path(client.folder_name, account, client.is_public_folder)
        if not folder.effective_rights.read:  # pylint: disable=E1101
            raise Exception(
                "Success to authenticate, but user has no permissions to read from the mailbox. "
                "Need to delegate the user permissions to the mailbox - "
                "please read integration documentation and follow the instructions"
            )
        folder.test_access()
    except ErrorFolderNotFound as e:
        if "Top of Information Store" in str(e):
            raise Exception(
                "Success to authenticate, but user probably has no permissions to read from the specific folder."
                "Check user permissions. You can try !ews-find-folders command to "
                "get all the folders structure that the user has permissions to"
            )

    demisto.results("ok")


def get_client_from_params(params: dict):
    """
    Constructs an EWSClient instance from the provided integration parameters.

    :param params: The dictionary received from demisto.params()

    :return: An EWSClient instance for interacting with the Exchange server.
    """
    username = params.get("credentials", {}).get("identifier")
    password = params.get("credentials", {}).get("password")
    access_type = IMPERSONATION if params.get("impersonation", False) else DELEGATE
    account_email = params.get("defaultTargetMailbox", "")
    max_fetch = min(50, int(params.get("maxFetch", 50)))
    ews_server = params.get("ewsServer", "")
    auth_type = params.get("authType", "")
    if auth_type:
        auth_type = parse_auth_type(auth_type)
    version = params.get("defaultServerVersion", "")
    folder = params.get("folder", "Inbox")
    is_public_folder = params.get("isPublicFolder", False)
    request_timeout = int(params.get("requestTimeout", 120))
    mark_as_read = params.get("markAsRead", False)
    manual_username = params.get("domainAndUserman", "")
    insecure = params.get("insecure", True)

    if ews_server and manual_username:
        username = manual_username

    return EWSClient(
        client_id=username,
        client_secret=password,
        access_type=access_type,
        default_target_mailbox=account_email,
        max_fetch=max_fetch,
        ews_server=ews_server,
        auth_type=auth_type,
        version=version,
        folder=folder,
        is_public_folder=is_public_folder,
        request_timeout=request_timeout,
        mark_as_read=mark_as_read,
        incident_filter=IncidentFilter.RECEIVED_FILTER,
        app_name=APP_NAME,
        insecure=insecure,
    )


def sub_main():  # pragma: no cover
    params = demisto.params()

    args = prepare_args(demisto.args())
    client = get_client_from_params(params)
    skip_unparsable_emails: bool = argToBoolean(params.get("skip_unparsable_emails", False))
    fetch_all_history = argToBoolean(demisto.params().get("fetchAllHistory", False))
    fetch_time = demisto.params().get("fetch_time") or "10 minutes"
    is_test_module = False

    fix_2010(client)

    try:
        if demisto.command() == "test-module":
            is_test_module = True
            test_module(client)
        elif demisto.command() == "fetch-incidents":
            incidents = fetch_emails_as_incidents(client, skip_unparsable_emails, fetch_all_history, fetch_time)
            demisto.incidents(incidents)
        elif demisto.command() == "ews-get-attachment":
            return_results(fetch_attachments_for_message(client, **args))
        elif demisto.command() == "ews-delete-attachment":
            return_results(delete_attachments_for_message(client, **args))
        elif demisto.command() == "ews-get-searchable-mailboxes":
            return_results(get_searchable_mailboxes(client))
        elif demisto.command() == "ews-search-mailboxes":
            return_results(search_mailboxes(client, **args))
        elif demisto.command() == "ews-move-item-between-mailboxes":
            return_results(move_item_between_mailboxes(client, **args))
        elif demisto.command() == "ews-move-item":
            return_results(move_item(client, **args))
        elif demisto.command() == "ews-delete-items":
            return_results(delete_items(client, **args))
        elif demisto.command() == "ews-search-mailbox":
            return_results(search_items_in_mailbox(client, **args))
        elif demisto.command() == "ews-get-contacts":
            return_results(get_contacts(client, **args))
        elif demisto.command() == "ews-get-out-of-office":
            return_results(get_out_of_office_state(client, **args))
        elif demisto.command() == "ews-recover-messages":
            return_results(recover_soft_delete_item(client, **args))
        elif demisto.command() == "ews-create-folder":
            return_results(create_folder(client, **args))
        elif demisto.command() == "ews-mark-item-as-junk":
            return_results(mark_item_as_junk(client, **args))
        elif demisto.command() == "ews-find-folders":
            return_results(find_folders(client, **args))
        elif demisto.command() == "ews-get-items-from-folder":
            return_results(get_items_from_folder(client, **args))
        elif demisto.command() == "ews-get-items":
            return_results(get_items(client, **args))
        elif demisto.command() == "ews-get-folder":
            return_results(get_folder(client, **args))
        elif demisto.command() == "ews-get-autodiscovery-config":
            return_results(get_autodiscovery_config())
        elif demisto.command() == "ews-expand-group":
            return_results(get_expanded_group(client, **args))
        elif demisto.command() == "ews-mark-items-as-read":
            return_results(mark_item_as_read(client, **args))
        elif demisto.command() == "ews-resolve-name":
            return_results(resolve_name_command(client, args))
        elif demisto.command() == "ews-get-items-as-eml":
            return_results(get_item_as_eml(client, **args))
        elif demisto.command() == "send-mail":
            return_results(send_email(client, args))
        elif demisto.command() == "reply-mail":
            return_results(reply_email(client, args))
        else:
            return_error(f'Command: "{demisto.command()}" was not recognized by this integration')

    except Exception as e:
        import time

        time.sleep(2)
        start_logging()
        debug_log = log_stream.getvalue()  # type: ignore
        error_message_simple = ""
        error_message = ""

        # Office365 regular maintenance case
        if (
            isinstance(e, ErrorMailboxMoveInProgress | ErrorMailboxStoreUnavailable)
            and urlparse(client.ews_server.lower()).hostname == "outlook.office365.com"
        ):
            log_message = (
                "Office365 is undergoing load balancing operations. As a result, the service is temporarily unavailable."
            )
            if demisto.command() == "fetch-incidents":
                demisto.info(log_message)
                demisto.incidents([])
                sys.exit(0)
            if is_test_module:
                demisto.results(log_message + " Please retry the instance configuration test.")
                sys.exit(0)
            error_message_simple = log_message + " Please retry your request."

        if isinstance(e, ConnectionError):
            error_message_simple = (
                "Could not connect to the server.\n"
                "Verify that the Hostname or IP address is correct.\n\n"
                f"Additional information: {e!s}"
            )
        if isinstance(e, ErrorInvalidPropertyRequest):
            error_message_simple = "Verify that the Exchange version is correct."
        else:
            from exchangelib.errors import MalformedResponseError

            if is_test_module and isinstance(e, MalformedResponseError):
                error_message_simple = (
                    "Got invalid response from the server.\nVerify that the Hostname or IP address is is correct."
                )

        # Legacy error handling
        if "Status code: 401" in debug_log:
            error_message_simple = (
                "Got unauthorized from the server. Check credentials are correct and authentication method are supported. "
            )

            error_message_simple += (
                "You can try using 'domain\\username' as username for authentication. "
                if client.auth_type.lower() == "ntlm"
                else ""
            )

        if "SSL: CERTIFICATE_VERIFY_FAILED" in debug_log:
            # same status code (503) but different error.
            error_message_simple = (
                "Certificate verification failed - This error may happen if the server "
                "certificate cannot be validated or as a result of a proxy that is doing SSL/TLS "
                "termination. It is possible to bypass certificate validation by checking "
                "'Trust any certificate' in the instance settings."
            )

        elif "Status code: 503" in debug_log:
            error_message_simple = (
                "Got timeout from the server. "
                "Probably the server is not reachable with the current settings. "
                "Check proxy parameter. If you are using server URL - change to server IP address. "
            )

        if not error_message_simple:
            error_message = error_message_simple = str(e)
        else:
            error_message = error_message_simple + "\n" + str(e)

        stacktrace = traceback.format_exc()
        if stacktrace:
            error_message += "\nFull stacktrace:\n" + stacktrace

        if debug_log:
            error_message += "\nFull debug log:\n" + debug_log

        if demisto.command() == "fetch-incidents":
            raise Exception(str(e) + traceback.format_exc())
        if demisto.command() == "ews-search-mailbox" and isinstance(e, ValueError):
            return_error(message="Selected invalid field, please specify valid field name.", error=e)
        if is_test_module:
            demisto.results(error_message_simple)
        else:
            demisto.results({"Type": entryTypes["error"], "ContentsFormat": formats["text"], "Contents": error_message_simple})
        demisto.error(f"{e.__class__.__name__}: {error_message}")
    finally:
        exchangelib_cleanup()
        if log_stream:
            try:
                logging.getLogger().removeHandler(log_handler)  # type: ignore
                log_stream.close()
            except Exception as ex:
                demisto.error(f"EWS: unexpected exception when trying to remove log handler: {ex}")


def process_main():  # pragma: no cover
    """setup stdin to fd=0 so we can read from the server"""
    sys.stdin = os.fdopen(0, "r")
    sub_main()


def main():  # pragma: no cover
    try:
        handle_proxy()
        # When running big queries, like 'ews-search-mailbox' the memory might not freed by the garbage
        # collector. `separate_process` flag will run the integration on a separate process that will prevent
        # memory leakage.
        separate_process = demisto.params().get("separate_process", False)
        demisto.debug(f"Running as separate_process: {separate_process}")
        if separate_process:
            try:
                p = Process(target=process_main)
                p.start()
                p.join()
            except Exception as ex:
                demisto.error(f"Failed starting Process: {ex}")
        else:
            sub_main()
    except Exception as exc:
        return_error(f"Found error in EWSv2: {exc}", error=f"Error: {exc}\nTraceback: {traceback.format_exc()}")


# python2 uses __builtin__ python3 uses builtins
if __name__ in ("__builtin__", "builtins", "__main__"):  # pragma: no cover
    main()
