from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def register(email, name):
    r=client.post('/auth/register',json={'email':email,'display_name':name,'password':'StrongPassword123!'})
    assert r.status_code==201, r.text
    return r.json()['access_token']

def setup_room(prefix='mod'):
    owner=register(f'{prefix}-owner@example.com','Owner')
    debater=register(f'{prefix}-debater@example.com','Debater')
    oh={'Authorization':f'Bearer {owner}'}; dh={'Authorization':f'Bearer {debater}'}
    debate=client.post('/debates',headers=oh,json={'title':'Evidence debate','fixed_question':'Should evidence be required in public policy debates?'}).json()
    invite=client.post(f"/debates/{debate['id']}/invitations",headers=oh,json={'invited_email':f'{prefix}-debater@example.com'}).json()
    p=client.post('/invitations/accept',headers=dh,json={'token':invite['invite_token'],'display_name':'Debater'}).json()
    client.put(f"/debates/{debate['id']}/room",headers=oh,json={'first_participant_id':p['id'],'turn_duration_seconds':300})
    return debate,p,owner,debater

def test_preview_detects_citation_and_pivot():
    debate,p,owner,debater=setup_room('preview')
    dh={'Authorization':f'Bearer {debater}'}
    result=client.post(f"/debates/{debate['id']}/turns/preview",headers=dh,json={'body':'What about a different scandal? The real issue is unrelated.'})
    assert result.status_code==200
    assert result.json()['pivot_detected'] is True
    assert result.json()['approved'] is False
    factual=client.post(f"/debates/{debate['id']}/turns/preview",headers=dh,json={'body':'The report shows a 35% increase in evidence use.'}).json()
    assert factual['citation_required'] is True
    assert factual['citation_present'] is False

def test_flagged_turn_enters_queue_and_owner_can_approve():
    debate,p,owner,debater=setup_room('queue')
    oh={'Authorization':f'Bearer {owner}'}; dh={'Authorization':f'Bearer {debater}'}
    flagged=client.post(f"/debates/{debate['id']}/turns",headers=dh,json={'body':'According to a report, evidence use increased 35%.'})
    assert flagged.status_code==422, flagged.text
    review_id=flagged.json()['detail']['review_id']
    reviews=client.get(f"/debates/{debate['id']}/moderation-reviews",headers=oh)
    assert reviews.status_code==200
    assert reviews.json()[0]['status']=='pending'
    decided=client.post(f'/moderation-reviews/{review_id}/decision',headers=oh,json={'approve':True,'note':'Citation supplied offline and verified.'})
    assert decided.status_code==200, decided.text
    assert decided.json()['status']=='approved'
    turns=client.get(f"/debates/{debate['id']}/turns",headers=oh).json()
    assert turns[-1]['body'].startswith('According to')
