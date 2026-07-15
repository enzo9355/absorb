# Security

- Secret identifiers and rotation: [`SECRETS.md`](../SECRETS.md)
- Trust boundaries: [`architecture_overview.md`](../architecture_overview.md)
- Incident response: [`runbook_incident_response.md`](../runbook_incident_response.md)

The LLM receives only bounded application-tool results and never receives direct database, filesystem, shell, token, or credential access.
