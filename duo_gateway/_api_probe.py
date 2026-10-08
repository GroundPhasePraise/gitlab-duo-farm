"""Test GitLab Duo via pure GraphQL API with PAT (no browser).
Uses tnmei41rc's admin PAT (config.yaml) against gitlab.com 19.5.
Steps: currentUser -> aiChatAvailableModels -> aiAction(DUO_CHAT) -> poll aiMessages.
"""
import json, time, urllib.request, urllib.error

GQL = "https://gitlab.com/api/graphql"
PAT = "REDACTED"
NS = "gid://gitlab/Group/142979973"

def call(query, variables=None, timeout=60):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(GQL, data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + PAT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code, "_body": e.read()[:400].decode(errors="replace")}
    except Exception as e:
        return {"_error": str(e)}

print("=== 1) currentUser ===")
d = call("query { currentUser { id username } }")
print(json.dumps(d, ensure_ascii=False)[:300])
cu = ((d.get("data") or {}).get("currentUser") or {})
USER_GID = cu.get("id") or "gid://gitlab/User/1"
print("USER_GID:", USER_GID)

print("=== 2) aiChatAvailableModels ===")
d = call("query { aiChatAvailableModels(namespaceId: \"%s\") { defaultModel { ref } selectableModels { ref provider } } }" % NS)
if d.get("_http_error"):
    print(d)
else:
    dm = (d.get("data") or {}).get("aiChatAvailableModels") or {}
    print("defaultModel:", dm.get("defaultModel"))
    mods = dm.get("selectableModels") or []
    print("models:", len(mods), [m.get("ref") for m in mods[:8]])

print("=== 3) aiAction (classic Duo Chat, old shape) ===")
d = call("""mutation aiAction($question: String!, $modelId: ModelID!, $resource: AiAgentResourceInput) {
  aiAction(input: { question: $question, modelId: $modelId, resource: $resource }) {
    errors, messageId, requestId, chatId
  }
}""", {"question": "Reply with exactly: API-DUO-OK", "modelId": "claude-sonnet-4-6",
      "resource": {"aiModelId": "claude-sonnet-4-6"}})
print(json.dumps(d, ensure_ascii=False)[:400])

print("=== 3b) aiAction (chat shape, conversationType DUO_CHAT) ===")
d = call("""mutation aiAction($input: AiActionInput!) {
  aiAction(input: $input) { errors, messageId, requestId, threadId }
}""", {"input": {"chat": {"content": "Reply with exactly: API-DUO-OK",
                          "resourceId": USER_GID},
                 "conversationType": "DUO_CHAT"}})
print(json.dumps(d, ensure_ascii=False)[:400])