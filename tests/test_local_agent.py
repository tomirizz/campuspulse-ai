import json
import httpx
import pytest
from campuspulse.local_agent import local_run, local_url


def test_remote_ollama_is_not_allowed(monkeypatch):
    monkeypatch.setenv('OLLAMA_URL','https://example.com')
    with pytest.raises(ValueError):local_url()


async def test_local_agent_contract_real_mcp_scripted_model(monkeypatch):
    """The model is scripted here; this is not a live-inference test."""
    monkeypatch.delenv('OLLAMA_URL',raising=False)
    calls=[]
    def handle(req):
        body=json.loads(req.content);calls.append(body)
        if 'action' in body.get('format',{}).get('properties',{}):
            return httpx.Response(200,json={'message':{'content':json.dumps({'action':'study_progress' if len(calls)==1 else 'finish'})}})
        return httpx.Response(200,json={'message':{'content':'{"fact_ids":["S2-2"],"explanation":"reward_rule","answer":"999 invented"}'}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        r=await local_run('Мой опыт?',{'tasks':[]},client=client)
    assert r['grounded'] and r['evidence'][0]['text']=='0'
    assert '999' not in r['answer']
    assert r['trace'][0]['transport']=='MCP · stdio'
    assert len(calls)==1
    assert r["trace"][1]["selection"] == "Правило запроса: обязательный источник"
