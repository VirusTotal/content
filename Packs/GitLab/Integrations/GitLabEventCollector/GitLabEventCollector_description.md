Gitlab Events Collector
-
 Collects the events log for events and audit events provided by Gitlab API.


---
* **Server URL** - The API domain URL for Gitlab.
* **API key** - The request API key, you can learn how to generate one [here](https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html).
* **Fetch Instance Audit Events** - Whether to fetch instance audit events. This type of fetch requires your token to have administrator authorization. See [PAT scopes](https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html). 
* **Groups IDs** - A comma-separated list of group IDs.
* **Projects IDs** - A comma-separated list of project IDs.
* **First fetch from API time** - The time to first fetch from the API.
* **The maximum number of events to fetch for each event type** - Each fetch will bring the `limit` number of events for each event type (audits, groups and projects) and each group/project ID. For example, if `limit` is set to 500 and groups/projects IDs are given as well, then the fetch will bring 500 audit events and 500 group/project events for each group/project ID.
