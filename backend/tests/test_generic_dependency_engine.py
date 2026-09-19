import unittest
from unittest.mock import patch

from app.core.demo_state import reset_demo_state
from app.engine.adapters import integration_health, set_integration_availability
from app.engine.adapters import request_registered_service
from app.engine.dependency_orchestrator import ensure_dependency, initiate_dependency
from app.engine.registry import CatalogConfigurationError, dependency_registry, select_dependency_provider
from app.core.persistence import ProviderCapabilityRow, ProviderRow, ServiceCatalogRow, Session, engine
from app.engine.consent_manager import create_consent


class GenericDependencyEngineTests(unittest.TestCase):
    def setUp(self):
        reset_demo_state()
        set_integration_availability("Revenue Department", True)
        set_integration_availability("Education Department", True)

    def _app(self, app_id, requirement_code):
        return {
            "appId": app_id,
            "citizenId": "CITIZEN_001",
            "status": "WAITING_FOR_DEPENDENCY",
            "dependencyIds": [],
            "dependencies": [],
            "requirements": [{"code": requirement_code, "status": "MISSING"}],
            "entityReviews": [],
            "conflictReviews": [],
            "statusHistory": [{"status": "WAITING_FOR_DEPENDENCY", "at": "2026-01-01T00:00:00+00:00"}],
        }

    def test_two_configured_capabilities_use_same_engine(self):
        health = integration_health()
        domicile_provider = select_dependency_provider("DOMICILE_PROOF", health)
        academic_provider = select_dependency_provider("ACADEMIC_RECORD", health)
        self.assertEqual(domicile_provider["serviceId"], "REV-MAHA-101")
        self.assertEqual(academic_provider["serviceId"], "EDU-ACA-201")

        domicile_app = self._app("GENERIC-DOMICILE", "DOMICILE_PROOF")
        academic_app = self._app("GENERIC-ACADEMIC", "ACADEMIC_RECORD")
        create_consent("CITIZEN_001", True)
        self.assertEqual(ensure_dependency(domicile_app, "DOMICILE_PROOF")["providerService"], "REV-MAHA-101")
        self.assertEqual(ensure_dependency(academic_app, "ACADEMIC_RECORD")["providerService"], "EDU-ACA-201")
        self.assertTrue(initiate_dependency("CITIZEN_001", academic_app, "ACADEMIC_RECORD")["success"])

    def test_capability_projection_is_authoritative_over_service_payload(self):
        capability = {"requirementCode": "CUSTOM_REQUIREMENT", "provider": "Provider B", "providerId": "PROVIDER-B", "requiredService": "Custom service", "serviceName": "Custom service", "serviceId": "SERVICE-B", "adapter": "REST API", "priority": 1}
        with patch("app.core.persistence.provider_capability_snapshot", return_value=[capability]):
            selected = select_dependency_provider("CUSTOM_REQUIREMENT", [{"system": "Provider B", "providerId": "PROVIDER-B", "status": "AVAILABLE"}])
        self.assertEqual(selected["providerId"], "PROVIDER-B")
        self.assertIsNone(select_dependency_provider("SERVICE_ONLY_PAYLOAD", [{"system": "Provider B", "providerId": "PROVIDER-B", "status": "AVAILABLE"}]))

    def test_production_catalog_failure_fails_closed_without_demo_fallback(self):
        with patch.dict("os.environ", {"SANGAM_ENV": "production", "SANGAM_ALLOW_DEMO_FALLBACK": "false"}), patch("app.core.persistence.provider_capability_snapshot", side_effect=RuntimeError("database unavailable")):
            with self.assertRaises(CatalogConfigurationError):
                dependency_registry([])

    def test_development_demo_fallback_requires_explicit_opt_in(self):
        with patch.dict("os.environ", {"SANGAM_ENV": "development", "SANGAM_ALLOW_DEMO_FALLBACK": "true"}), patch("app.core.persistence.catalog_snapshot", side_effect=RuntimeError("database unavailable")):
            from app.engine.registry import get_scheme
            self.assertIsNotNone(get_scheme("SCH-MH-2026"))

    def test_available_provider_wins_over_unhealthy_provider(self):
        candidates = [
            {"requirementCode": "CUSTOM", "provider": "Unhealthy", "providerId": "UNHEALTHY", "requiredService": "Custom", "serviceName": "Custom", "serviceId": "S-1", "adapter": "REST API", "priority": 1},
            {"requirementCode": "CUSTOM", "provider": "Healthy", "providerId": "HEALTHY", "requiredService": "Custom", "serviceName": "Custom", "serviceId": "S-2", "adapter": "REST API", "priority": 10},
        ]
        with patch("app.core.persistence.provider_capability_snapshot", return_value=candidates):
            selected = select_dependency_provider("CUSTOM", [{"system": "Unhealthy", "providerId": "UNHEALTHY", "status": "UNAVAILABLE"}, {"system": "Healthy", "providerId": "HEALTHY", "status": "AVAILABLE"}])
        self.assertEqual(selected["providerId"], "HEALTHY")

    def test_provider_execution_requires_active_capability_provider_and_service(self):
        from unittest.mock import patch
        with patch("app.engine.adapters.integration_health", return_value=[{"system": "Revenue Department", "status": "AVAILABLE"}]):
            with Session(engine) as session:
                service = session.get(ServiceCatalogRow, "REV-MAHA-101")
                capability = session.query(ProviderCapabilityRow).filter_by(service_id=service.service_id).first()
                provider = session.get(ProviderRow, service.provider_id)
                original = (capability.enabled, provider.active, service.active)
                try:
                    session.delete(capability)
                    session.commit()
                    self.assertFalse(request_registered_service(service.service_id, "CITIZEN_001", requirement_code="DOMICILE_PROOF").success)
                    capability = ProviderCapabilityRow(capability_id=f"TEST:{service.service_id}", provider_id=provider.provider_id, capability_code="DOMICILE_PROOF", service_id=service.service_id, enabled=False, payload={})
                    session.add(capability)
                    session.commit()
                    self.assertFalse(request_registered_service(service.service_id, "CITIZEN_001", requirement_code="DOMICILE_PROOF").success)
                    capability.enabled = True
                    session.commit()
                    provider.active = False
                    session.commit()
                    self.assertFalse(request_registered_service(service.service_id, "CITIZEN_001", requirement_code="DOMICILE_PROOF").success)
                    provider.active = original[1]
                    service.active = False
                    session.commit()
                    self.assertFalse(request_registered_service(service.service_id, "CITIZEN_001", requirement_code="DOMICILE_PROOF").success)
                finally:
                    session.query(ProviderCapabilityRow).filter_by(service_id=service.service_id).delete(synchronize_session=False)
                    session.add(ProviderCapabilityRow(capability_id=f"{provider.provider_id}:DOMICILE_PROOF", provider_id=provider.provider_id, capability_code="DOMICILE_PROOF", service_id=service.service_id, enabled=original[0], payload={}))
                    provider.active, service.active = original[1], original[2]
                    session.commit()


if __name__ == "__main__":
    unittest.main()
