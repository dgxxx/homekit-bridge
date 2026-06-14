---
name: project-homekit-overview
description: Überblick über das homekit-Projekt — Ziel, Architektur, Phasen, Scope
metadata:
  type: project
---

Lokale HomeKit-Bridge in Python, die Homematic CCU3 (lesen + schalten) und SolarEdge PV (nur lesen) als native HomeKit-Accessories darstellt. Web-UI zur Konfiguration via FastAPI + Vanilla-JS.

**Why:** User will eigene Geräte ohne Cloud-Abhängigkeit in Apple Home integrieren.

**How to apply:** Scope: nur CCU3 + SolarEdge, lokal, Anzeigen + Schalten (keine Automatisierungen). Seit dem MQTT-Refactor (v2) ist die Bridge reiner MQTT-Konsument — die Quell-Dienste `ccu3` und `solaredge` publishen auf den Broker, direkte XML-RPC-/Modbus-Adapter sind entfernt.

Phasen: 0-1 Scaffold/Core → 2 CCU3 → 3 SolarEdge → 4 Mapper → 5 HAP → 6 API → 7 Frontend → 8 Docker/README → MQTT-Refactor (E1-E5).

Stand 2026-06-14: v2 (MQTT-Refactor) abgeschlossen, Repo public; READMEs (DE+EN) auf MQTT-Architektur aktualisiert.

Verknüpft: [[project-homekit-scope-v1]]
