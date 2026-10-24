import pytest
from app import app

@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def test_home_page(client):
    response = client.get('/')

    assert response.status_code == 200
    assert response.get_json() == {"message": "Flask CI/CD demo is running"}


def test_health_reports_application_ready(client):
    response = client.get('/health')

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_unknown_route_returns_not_found(client):
    response = client.get('/not-a-route')

    assert response.status_code == 404
