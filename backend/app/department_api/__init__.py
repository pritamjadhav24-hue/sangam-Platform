"""Simulated Maharashtra government department REST APIs.

This is the ONLY code allowed to read or write a department sandbox database
(``app.sandbox.<department>``). SANGAM itself never imports this package or
``app.sandbox`` directly -- it reaches a department exclusively through the
HTTP endpoints defined here, via ``app.engine.adapters.DepartmentSandboxAPIAdapter``.

Every response is explicitly marked ``synthetic: true`` with a disclaimer.
This is a simulated environment, never a live government integration.
"""
