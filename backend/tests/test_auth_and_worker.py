from fastapi.testclient import TestClient
from app.main import app
client = TestClient(app)
import time

def test_registration_login_and_dashboard():
    registration = client.post('/auth/register', json={
        'email': 'builder@example.com', 'display_name': 'EPIC Builder', 'password': 'strongpass123'
    })
    assert registration.status_code == 201
    token = registration.json()['access_token']
    headers = {'Authorization': f'Bearer {token}'}
    me = client.get('/auth/me', headers=headers)
    assert me.status_code == 200
    assert me.json()['display_name'] == 'EPIC Builder'
    dashboard = client.get('/dashboard/summary', headers=headers)
    assert dashboard.status_code == 200
    assert dashboard.json()['counts']['debates'] >= 0
    login = client.post('/auth/login', json={'email':'builder@example.com','password':'strongpass123'})
    assert login.status_code == 200
    logout = client.post('/auth/logout', headers={'Authorization': f'Bearer {login.json()["access_token"]}'})
    assert logout.status_code == 204
    assert client.get('/auth/me', headers={'Authorization': f'Bearer {login.json()["access_token"]}'}).status_code == 401


def test_automatic_research_worker_advances_job():
    created = client.post('/knowledge/jobs/auto', json={'query':'Test background research','dossier_id':None})
    assert created.status_code == 201
    job_id = created.json()['id']
    deadline = time.time() + 2
    current = None
    while time.time() < deadline:
        current = client.get(f'/knowledge/jobs/{job_id}').json()
        if current['status'] == 'not_implemented':
            break
        time.sleep(.04)
    assert current['status'] == 'not_implemented'
    assert current['progress_percent'] == 0
    assert current['result_summary'] is None
    assert 'not implemented' in current['error_message'].lower()
    events = client.get(f'/knowledge/jobs/{job_id}/events').json()
    assert events[-1]['step'] == 'Automated research is not implemented'
    assert all('Searching registered sources' not in event['step'] for event in events)
