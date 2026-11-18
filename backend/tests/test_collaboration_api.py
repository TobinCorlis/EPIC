from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def register(email, name):
    r = client.post('/auth/register', json={'email': email, 'display_name': name, 'password': 'StrongPassword123!'})
    assert r.status_code == 201, r.text
    return r.json()['access_token']


def test_invitation_acceptance_and_event_history():
    owner_token = register('owner-collab@example.com', 'Owner Collab')
    guest_token = register('guest-collab@example.com', 'Guest Collab')
    owner_headers = {'Authorization': f'Bearer {owner_token}'}
    guest_headers = {'Authorization': f'Bearer {guest_token}'}

    debate = client.post('/debates', headers=owner_headers, json={
        'title': 'Collaboration test',
        'fixed_question': 'Should verified evidence be required?',
        'description': 'Invitation workflow'
    })
    assert debate.status_code == 201, debate.text
    debate_id = debate.json()['id']

    invite = client.post(f'/debates/{debate_id}/invitations', headers=owner_headers, json={
        'invited_email': 'guest-collab@example.com',
        'participant_role': 'debater',
        'side': 'affirmative',
        'expires_in_hours': 24,
        'max_uses': 1
    })
    assert invite.status_code == 201, invite.text
    raw_token = invite.json()['invite_token']
    assert raw_token

    accepted = client.post('/invitations/accept', headers=guest_headers, json={
        'token': raw_token,
        'display_name': 'Guest Advocate'
    })
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()['side'] == 'affirmative'

    events = client.get(f'/debates/{debate_id}/events')
    assert events.status_code == 200
    assert any(event['event_type'] == 'participant.joined' for event in events.json())

    reused = client.post('/invitations/accept', headers=guest_headers, json={
        'token': raw_token,
        'display_name': 'Another Name'
    })
    assert reused.status_code == 410


def test_invitation_email_binding():
    owner_token = register('owner-binding@example.com', 'Owner Binding')
    wrong_token = register('wrong-binding@example.com', 'Wrong Guest')
    h = {'Authorization': f'Bearer {owner_token}'}
    debate = client.post('/debates', headers=h, json={'title':'Bound invite','fixed_question':'Is identity binding useful?'}).json()
    invite = client.post(f"/debates/{debate['id']}/invitations", headers=h, json={'invited_email':'right@example.com'}).json()
    result = client.post('/invitations/accept', headers={'Authorization': f'Bearer {wrong_token}'}, json={'token':invite['invite_token'], 'display_name':'Wrong'})
    assert result.status_code == 403
