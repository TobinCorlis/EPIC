from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def register(email, name):
    r = client.post('/auth/register', json={'email': email, 'display_name': name, 'password': 'StrongPassword123!'})
    assert r.status_code == 201, r.text
    return r.json()['access_token']


def test_turn_order_and_reconnect_safe_state():
    owner_token = register('turn-owner@example.com', 'Turn Owner')
    first_token = register('turn-first@example.com', 'First Debater')
    second_token = register('turn-second@example.com', 'Second Debater')
    oh = {'Authorization': f'Bearer {owner_token}'}
    debate = client.post('/debates', headers=oh, json={'title':'Turn order','fixed_question':'Should turns be enforced?'}).json()
    participants=[]
    for email, token, name, side in [
        ('turn-first@example.com', first_token, 'First', 'affirmative'),
        ('turn-second@example.com', second_token, 'Second', 'negative'),
    ]:
        invite=client.post(f"/debates/{debate['id']}/invitations", headers=oh, json={'invited_email':email,'side':side}).json()
        accepted=client.post('/invitations/accept', headers={'Authorization':f'Bearer {token}'}, json={'token':invite['invite_token'],'display_name':name})
        assert accepted.status_code == 200, accepted.text
        participants.append(accepted.json())
    configured=client.put(f"/debates/{debate['id']}/room", headers=oh, json={'turn_duration_seconds':120,'first_participant_id':participants[0]['id']})
    assert configured.status_code == 200
    wrong=client.post(f"/debates/{debate['id']}/turns", headers={'Authorization':f'Bearer {second_token}'}, json={'body':'I should not post first.'})
    assert wrong.status_code == 409
    first=client.post(f"/debates/{debate['id']}/turns", headers={'Authorization':f'Bearer {first_token}'}, json={'body':'My supported opening statement.'})
    assert first.status_code == 201, first.text
    state=client.get(f"/debates/{debate['id']}/room", headers={'Authorization':f'Bearer {second_token}'})
    assert state.status_code == 200
    assert state.json()['current_participant_id'] == participants[1]['id']
    second=client.post(f"/debates/{debate['id']}/turns", headers={'Authorization':f'Bearer {second_token}'}, json={'body':'My response.'})
    assert second.status_code == 201
    turns=client.get(f"/debates/{debate['id']}/turns", headers=oh).json()
    assert [t['body'] for t in turns] == ['My supported opening statement.', 'My response.']
    events=client.get(f"/debates/{debate['id']}/events").json()
    assert any(e['event_type']=='turn.submitted' for e in events)
    assert any(e['event_type']=='turn.advanced' for e in events)


def test_owner_can_skip_a_turn():
    owner_token=register('skip-owner@example.com','Skip Owner')
    guest_token=register('skip-guest@example.com','Skip Guest')
    oh={'Authorization':f'Bearer {owner_token}'}
    debate=client.post('/debates',headers=oh,json={'title':'Skip','fixed_question':'Can stalled turns advance?'}).json()
    inv=client.post(f"/debates/{debate['id']}/invitations",headers=oh,json={'invited_email':'skip-guest@example.com'}).json()
    p=client.post('/invitations/accept',headers={'Authorization':f'Bearer {guest_token}'},json={'token':inv['invite_token'],'display_name':'Guest'}).json()
    client.put(f"/debates/{debate['id']}/room",headers=oh,json={'first_participant_id':p['id'],'turn_duration_seconds':30})
    skipped=client.post(f"/debates/{debate['id']}/turns/skip",headers=oh)
    assert skipped.status_code == 200
    turns=client.get(f"/debates/{debate['id']}/turns",headers=oh).json()
    assert turns[0]['status']=='skipped'
