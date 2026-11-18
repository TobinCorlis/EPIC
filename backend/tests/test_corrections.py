from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_uncertainty_and_corrections_are_visible_in_reads_and_exports():
    debate = client.post(
        "/debates",
        json={"title": "Correction debate", "fixed_question": "Does the record support the finding?"},
    ).json()
    created = client.post(
        f"/debates/{debate['id']}/claims",
        json={
            "body": "The record supports the finding.",
            "claim_type": "factual",
            "uncertainty": "The page number was not checked against the PDF.",
        },
    )
    assert created.status_code == 201, created.text
    claim_id = created.json()["id"]
    assert created.json()["uncertainty"].startswith("The page number")
    assert created.json()["corrections"] == []

    anonymous = client.post(
        f"/claims/{claim_id}/corrections",
        json={"corrected_body": "The record supports the finding on page 4.", "reason": "The page was checked."},
    )
    assert anonymous.status_code == 401

    account = client.post(
        "/auth/register",
        json={"email": "corrector@example.com", "display_name": "Corrector", "password": "verysecure123"},
    ).json()
    headers = {"Authorization": f"Bearer {account['access_token']}"}
    corrected = client.post(
        f"/claims/{claim_id}/corrections",
        headers=headers,
        json={
            "corrected_body": "The record supports the finding on page 4.",
            "reason": "The page was checked against the PDF.",
            "uncertainty": "The PDF hash was not recorded.",
        },
    )
    assert corrected.status_code == 200, corrected.text
    body = corrected.json()
    assert body["body"].endswith("page 4.")
    assert body["uncertainty"] == "The PDF hash was not recorded."
    assert body["corrections"][0]["original_body"] == "The record supports the finding."
    assert body["corrections"][0]["author_user_id"] == account["user"]["id"]
    assert body["corrections"][0]["reason"].startswith("The page was checked")
    assert body["corrections"][0]["created_at"]

    listed = client.get(f"/debates/{debate['id']}/claims").json()
    assert listed[0]["corrections"][0]["corrected_body"].endswith("page 4.")

    export = client.get(f"/debates/{debate['id']}/export").json()
    assert export["claims"][0]["uncertainty"] == "The PDF hash was not recorded."
    assert export["claims"][0]["corrections"][0]["original_body"] == "The record supports the finding."
    markdown = client.get(f"/debates/{debate['id']}/export.md").text
    assert "Uncertainty: The PDF hash was not recorded." in markdown
    assert "corrected to" in markdown

    dossier = client.post(
        "/knowledge/dossiers",
        json={"title": "Correction dossier", "question": "Which text is current?"},
    ).json()
    knowledge = client.post(
        f"/knowledge/dossiers/{dossier['id']}/claims",
        json={"body": "The policy reduced incidents.", "uncertainty": "The county definition is unresolved."},
    ).json()
    assert knowledge["uncertainty"].startswith("The county")
    updated = client.post(
        f"/knowledge/claims/{knowledge['id']}/corrections",
        headers=headers,
        json={
            "corrected_body": "The policy reduced reported incidents.",
            "reason": "The original omitted the word reported.",
        },
    )
    assert updated.status_code == 200, updated.text
    listed_knowledge = client.get(f"/knowledge/dossiers/{dossier['id']}/claims").json()
    assert listed_knowledge[0]["body"].startswith("The policy reduced reported")
    assert listed_knowledge[0]["corrections"][0]["original_body"] == "The policy reduced incidents."
    assert listed_knowledge[0]["uncertainty"].startswith("The county")
