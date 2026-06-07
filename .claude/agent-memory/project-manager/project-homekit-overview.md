---
name: project-homekit-overview
description: Überblick über das homekit-Projekt — Ziel, Architektur, Phasen, Scope
metadata:
  type: project
---

Lokale HomeKit-Bridge in Python, die SolarEdge PV (Modbus TCP) und Homematic CCU3 (XML-RPC) als native HomeKit-Accessories darstellt. Web-UI zur Konfiguration via FastAPI + Vanilla-JS.

**Why:** User will eigene Geräte ohne Cloud-Abhängigkeit in Apple Home integrieren.

**How to apply:** Scope streng auf v1 halten — nur SolarEdge + CCU3, nur lokale Protokolle, nur Anzeige (kein Schreiben/Automatisieren).

Phasen: 0-1 Scaffold/Core → 2 CCU3 → 3 SolarEdge → 4 Mapper → 5 HAP → 6 API → 7 Frontend → 8 Docker/README

Stand 2026-06-07: Phase 0-1 (Scaffold + Core) in Arbeit (Task #11).

Verknüpft: [[project-homekit-scope-v1]]
