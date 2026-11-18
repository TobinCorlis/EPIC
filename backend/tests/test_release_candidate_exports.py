from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_claim_listing_and_debate_exports():
    debate = client.post('/debates', json={'title':'Export test','fixed_question':'Does the record support the proposition?','description':'RC2 export test'}).json()
    claim = client.post(f"/debates/{debate['id']}/claims", json={'body':'The record supports the proposition.','claim_type':'factual'}).json()
    listed = client.get(f"/debates/{debate['id']}/claims")
    assert listed.status_code == 200
    assert [row['id'] for row in listed.json()] == [claim['id']]

    source = client.post('/sources', json={'title':'Official export record','url':'https://example.gov/export-record','publisher':'Example Agency','source_type':'government_record'}).json()
    citation = client.post('/citations', json={'source_id':source['id'],'locator':'p. 7'}).json()
    client.post(f"/claims/{claim['id']}/evidence", json={'citation_id':citation['id'],'stance':'supports','relevance_score':0.9,'claim_supported':'The record supports the proposition.'})

    export = client.get(f"/debates/{debate['id']}/export")
    assert export.status_code == 200
    assert export.json()['debate']['title'] == 'Export test'
    assert export.json()['claims'][0]['body'] == 'The record supports the proposition.'
    assert export.json()['evidence'][0]['citation']['source']['title'] == 'Official export record'

    markdown = client.get(f"/debates/{debate['id']}/export.md")
    assert markdown.status_code == 200
    assert '# Export test' in markdown.text
    assert 'Official export record' in markdown.text
