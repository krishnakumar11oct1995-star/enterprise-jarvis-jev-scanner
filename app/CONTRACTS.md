# Salesforce Jarvis PC Application: System Architecture & Thread Contract Specification

**Document Version:** 2.1.0  
**Target Platform:** Windows 10/11 x64  
**Runtime:** Python 3.12+ (Python 3.14 compatible)  
**Memory Budget:** < 75.0 MB Working Set RAM  
**Process Mode:** Stealth Background Daemon (Zero Black Console Flash, `pythonw.exe` / `CREATE_NO_WINDOW = 0x08000000`)

---

## 1. System Architecture Overview

The **Salesforce Jarvis PC Application** is an ambient desktop daemon and developer companion designed to continuously monitor connected Salesforce orgs (Alliance Prod, TeamMD, TeamHotfix), track real-time platform events, execute 4-tier telemetry observability, detect multi-cloud architectural conflicts, present a modern dark-glass desktop Heads-Up Display (HUD) cockpit, synthesize British Butler audio briefings (`edge-tts` / SAPI5), and dock seamlessly into the Windows System Tray.

```
+----------------------------------------------------------------------------------------------------+
|                                      MAIN APPLICATION SUPERVISOR                                   |
|                                            (app/main.py)                                           |
+----------------------------------------------------------------------------------------------------+
                   │                                                                 │
      (Inter-Thread Event Bus)                                          (Lifecycle & Signal Manager)
                   ▼                                                                 ▼
+──────────────────────────────────────────────────+             +───────────────────────────────────+
|               THREAD-SAFE EVENT BUS              |             |        SUPERVISOR WATCHDOG        |
|                (app/event_bus.py)                |             |  - Memory Watchdog (<75MB RAM)    |
+──────────────────────────────────────────────────+             |  - Subprocess Silent Flags        |
         ▲              ▲             ▲             ▲            |  - Graceful Shutdown Coordinator  |
         │              │             │             │            +───────────────────────────────────+
         │              │             │             │
+─────────────────+  +─────────────────+  +─────────────────+  +─────────────────────────────────────+
|   MILESTONE 1   |  |   MILESTONE 2   |  |   MILESTONE 3   |  |             MILESTONE 4             |
|   TRAY DAEMON   |  |    SF POLLER    |  |     HUD UI      |  |            VOICE ENGINE             |
+─────────────────+  +─────────────────+  +─────────────────+  +─────────────────────────────────────+
| `app/tray.py`   |  |`app/sf_poller.py|  | `app/ui/hud.py` |  | `app/voice.py`                      |
| `app/startup.py`|  |                 |  | `app/ui/web/`   |  | - British Butler TTS (edge-tts   |
| `app/notify.py` |  | - 4-Tier Engine |  |   index.html    |  |   `en-GB-RyanNeural` / SAPI5)    |
| - pystray daemon|  | - 7 Corrections |  |   style.css     |  | - Spoken Executive Morning       |
| - Green/Yellow/ |  | - CLI Subprocess|  |   app.js        |  |   Briefing                          |
|   Red status    |  |   CREATE_NO_    |  | - Dark Glass HUD|  | - Non-blocking Audio Playback   |
| - Startup link  |  |   WINDOW        |  | - Global Alt+J  |  | - Instant Mute Toggle               |
| - Windows Toast |  | - Offline cache |  | - 4-Tier Gauges |  | - Tier 1-4 Vocal Telemetry      |
|   Notifications |  | - Conflict Radar|  | - FTS5 Search   |  |                                     |
+─────────────────+  +─────────────────+  +─────────────────+  +─────────────────────────────────────+
```

---

## 2. Milestone Contract Specifications

### 2.1 Milestone 1: Windows Boot Auto-Start, System Tray & Toast Notifications
- **Files:**
  - `app/startup.py`: Configures Windows Startup folder (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`) via silent VBS or `.lnk` shortcut pointing to `pythonw.exe app/main.py`. Ensures zero console flashing on boot.
  - `app/notify.py`: Native Windows Toast notifications. Uses Windows WinRT / PowerShell fallback or BurntToast. Displays alerts on critical batch failures, stranded records, or radar conflicts.
  - `app/tray.py`: System Tray integration using `pystray`. Provides:
    - Dynamic icon color states: `Green` (Nominal), `Yellow` (Warning / Minor Drift), `Red` (Critical Failure / Conflicts), `Blue` (Active Polling / Syncing).
    - Context Menu items:
      - `Open HUD Cockpit` (Triggers HUD display / Alt+J)
      - `Run Executive Briefing` (Invokes Voice Engine morning briefing)
      - `Scan Orgs & Conflicts` (Triggers immediate telemetry & radar pass)
      - `Mute / Unmute Voice` (Toggles TTS audio)
      - `Exit Jarvis` (Executes unified clean shutdown)

### 2.2 Milestone 2: Background Salesforce Live Telemetry & Poller Daemon
- **File:** `app/sf_poller.py`
- **Class:** `SalesforcePoller`
- **Threading Model:** Background worker thread (`daemon=True`) polling at configurable intervals (default: 30s to 15m).
- **Subprocess Isolation:** Every `sf` or `sfdx` CLI call MUST specify `creationflags=0x08000000` (`subprocess.CREATE_NO_WINDOW`) to eliminate black command prompt flashes.
- **Core Scope:** Executes the comprehensive **4-Tier Observability Specification** and incorporates all **7 Platform Engineering Corrections**.
- **Resilience:** Local JSON caching (`app/telemetry_cache.json` and `app/state.json`). Offline and mock mode fallback when disconnected. Emits telemetry snapshot dictionary over `default_event_bus`.

### 2.3 Milestone 3: Modern Desktop HUD Cockpit UI
- **Files:**
  - `app/ui/hud.py`: Window manager using `pywebview` or lightweight local HTTP server + native browser window (`frameless=True, on_top=True`).
  - `app/ui/server.py`: FastAPI / Starlette server delivering live JSON telemetry and REST endpoints.
  - `app/ui/web/index.html`, `app/ui/web/style.css`, `app/ui/web/app.js`:
    - Dark-mode glassmorphic Arc-Reactor aesthetic with cyan/teal/emerald telemetry accents.
    - Global hotkey listener for `Alt + J`.
    - Live Org Status Grid (Alliance Prod, TeamMD, TeamHotfix).
    - 4-Tier Observability telemetry cards (Tier 1 Failures, Tier 2 Integrations, Tier 3 Governance, Tier 4 Hygiene).
    - Active batch monitor progress/status bars.
    - Stranded encounters & denial metric badges.
    - Drag-and-drop code triage dropzone for instant Conflict Radar evaluation.
    - Memory Search input querying `Antigravity Index` (`index.sqlite`) using FTS5.

### 2.4 Milestone 4: Voice Engine & Spoken Executive Morning Briefing
- **Files:** `app/voice.py`, `app/briefing.py`
- **Class:** `VoiceEngine`
- **Voice Synthesis:**
  - High-definition British Butler neural voice using `edge-tts` (`en-GB-RyanNeural` or `en-GB-SoniaNeural`).
  - Fallback to Windows SAPI5 (`win32com.client.Dispatch("SAPI.SpVoice")`) or Windows PowerShell SpeechSynthesizer if offline.
  - Zero external paid API key requirement.
- **Audio Playback:**
  - Non-blocking audio playback using Windows MCI / winsound / pygame.
  - Priority audio queue to prevent overlapping speech.
  - Global mute state toggled via tray or HUD.
- **Executive Morning Briefing:**
  - Formats 4-tier telemetry snapshot into an articulate, executive briefing:
    *"Good morning, sir. Jarvis live telemetry report. Alliance Production and TeamMD orgs are connected. Tier 1 failure signals are nominal with zero unhandled batch exceptions. Tier 2 integration flows report Bulk API ingestion at 100% success, and Snowflake replication high-water marks are synchronized. Tier 3 governance shows zero out-of-band direct production modifications and test coverage holding at 84%. Tier 4 platform hygiene indicates active sessions and storage gauges are well within enterprise thresholds. All systems operating nominally."*

---

## 3. Four-Tier Observability Specification

The Jarvis 2.0 Flight Deck implements an exhaustive 4-tier observability framework covering real-time platform events, integration pipelines, governance metadata, and operational platform hygiene.

```
+────────────────────────────────────────────────────────────────────────────────────────────────────+
|                                4-TIER OBSERVABILITY SPECIFICATION                                  |
+────────────────────────────────────────────────────────────────────────────────────────────────────+
| TIER 1: REAL-TIME FAILURE SIGNALS                                                                  |
| - BatchApexErrorEvent      : Streaming unhandled exceptions in Apex batch EXECUTE phase            |
| - FlowExecutionErrorEvent  : Real-time platform event on unhandled Flow faults & failed interviews |
| - FlowInterview            : Polling paused and failed flow interviews (Error / Paused status)     |
| - CronTrigger              : Scheduled Apex heartbeat, NextFireTime & missed fire sentinel        |
| - EventLogFile (Free)      : Standard ApexUnexpectedException log parsing without paid license    |
+----------------------------------------------------------------------------------------------------+
| TIER 2: INTEGRATION & API ATTRIBUTION                                                             |
| - Bulk API 2.0 Jobs        : Ingest & Query job progress, failed records, state, duration          |
| - API Attribution          : Usage attribution breakdown by ConnectedApp and User                  |
| - Certificate & OAuth      : X.509 cert expiration & OAuth token refresh across 3 orgs             |
| - SF <-> Snowflake Reconcil: Row count & MAX(SystemModstamp) high-water mark verification          |
+----------------------------------------------------------------------------------------------------+
| TIER 3: CHANGE & GOVERNANCE                                                                        |
| - SetupAuditTrail          : Sentinel for direct-prod modifications bypassing CI/CD pipeline       |
| - Cross-Org Metadata Drift : Apex class, Flow, and CustomField hash comparison across orgs         |
| - ApexOrgWideCoverage      : 75% deployment threshold sentinel & ApexTestRunResult tracker         |
| - SandboxProcess           : Freshness tracking & staleness alerting (>30/60 days since refresh)   |
+----------------------------------------------------------------------------------------------------+
| TIER 4: PLATFORM HYGIENE & SLAS                                                                    |
| - AuthSession Active Users : Concurrent active UI sessions, login spikes, session anomalies        |
| - Storage Gauges           : Data Storage & File Storage % utilization vs licensed headroom        |
| - Data Quality Null Probes : Statistical null-rate sampling on mandatory operational SObject fields|
| - Time-in-Queue SLAs       : AsyncApexJob & queue dwell times vs enterprise SLA thresholds         |
| - Salesforce Trust API     : Real-time instance pod status & incidents from api.status.salesforce  |
+----------------------------------------------------------------------------------------------------+
```

### 3.1 Tier 1: Real-Time Failure Signals
Tier 1 captures immediate execution breakages before end users report them.
1. **`BatchApexErrorEvent`:**
   - **Mechanism:** Standard Salesforce platform event automatically published when a batch job encounters an unhandled exception in its `EXECUTE` phase.
   - **Fields Extracted:** `AsyncApexJobId`, `JobScope`, `ExceptionType`, `Message`, `StackTrace`, `Phase`.
   - **Contract:** Poller or event listener ingests events, flags associated job as `CRITICAL`, and dispatches immediate desktop toast notification and audio alert.
2. **`FlowExecutionErrorEvent`:**
   - **Mechanism:** Standard platform event published when a record-triggered flow, scheduled flow, or autolaunched flow fails with an unhandled fault.
   - **Fields Extracted:** `InterviewGuid`, `FlowApiName`, `FlowVersionNumber`, `Stage`, `ElementApiName`, `ErrorMessage`.
   - **Contract:** Identifies broken declarative automations, maps the faulty element ID, and raises an alert.
3. **`FlowInterview` Querying:**
   - **Mechanism:** SOQL probe against paused or failed interviews:
     ```sql
     SELECT Id, FlowInterviewLabel, InterviewStatus, CurrentElement, LastModifiedDate 
     FROM FlowInterview 
     WHERE InterviewStatus IN ('Error', 'Paused') 
     ORDER BY LastModifiedDate DESC LIMIT 25
     ```
   - **Contract:** Detects silent flow hang-ups and unhandled pause conditions.
4. **`CronTrigger` Scheduled Job Sentinel:**
   - **Mechanism:** SOQL probe evaluating scheduled Apex and platform jobs:
     ```sql
     SELECT Id, CronJobDetail.Name, CronJobDetail.JobType, State, NextFireTime, PreviousFireTime, TimesTriggered 
     FROM CronTrigger 
     WHERE State IN ('ERROR', 'BLOCKED') OR NextFireTime < YESTERDAY
     ```
   - **Contract:** Alerts if critical nightly batches (e.g. `YesterdayDenialSyncBatch`) miss scheduled execution windows or enter `BLOCKED` states.
5. **Free `EventLogFile` Unexpected Exceptions:**
   - **Mechanism:** Queries standard 24-hour log files available in Salesforce Standard Edition without requiring a paid Event Monitoring license:
     ```sql
     SELECT Id, EventType, LogDate, LogFileLength FROM EventLogFile 
     WHERE EventType = 'ApexUnexpectedException' AND LogDate = TODAY
     ```
   - **Contract:** Parses unexpected runtime crashes, unhandled Aura/LWC exceptions, and critical governor limit breaches.

---

### 3.2 Tier 2: Integration & API Attribution
Tier 2 monitors enterprise data bridges and API consumption.
1. **Bulk API 2.0 Ingest & Query Jobs:**
   - **Mechanism:** Ingestion and Query monitoring via REST endpoints (`/services/data/v60.0/jobs/ingest` and `/jobs/query`).
   - **Fields Monitored:** `id`, `state` (`Open`, `UploadComplete`, `InProgress`, `JobComplete`, `Failed`, `Aborted`), `numberRecordsProcessed`, `numberRecordsFailed`, `totalProcessingTime`, `apiActiveProcessingTime`.
   - **Contract:** Raises warning if `numberRecordsFailed > 0` or if job duration exceeds 45 minutes.
2. **API Total Usage by App/User Attribution:**
   - **Mechanism:** Disaggregates `DailyApiRequests` usage by Connected App / Client Name and User ID.
   - **Contract:** Attributes API consumption spikes to specific systems (e.g., MuleSoft integrations, Snowflake reverse ETL, CareCloud connector) and alerts when any single integration consumes > 50% of the daily limit.
3. **Certificate & OAuth Token Expiry across Orgs:**
   - **Mechanism:** Evaluates certificates and connected app tokens across Alliance Prod, TeamMD, and TeamHotfix:
     ```sql
     SELECT Id, MasterLabel, DeveloperName, ExpirationDate FROM Certificate
     ```
   - **Contract:** Emits a warning at 30 days prior to expiry, and a critical alert at 7 days prior to expiry.
4. **Salesforce <-> Snowflake Reconciliation:**
   - **Mechanism:** Cross-cloud reconciliation comparing Salesforce source table metrics against Snowflake replica tables:
     - Salesforce: `SELECT COUNT(Id), MAX(SystemModstamp) FROM <SObject>`
     - Snowflake: `SELECT COUNT(*), MAX(SystemModstamp) FROM SF_STAGE.<SOBJECT>_RAW`
   - **Contract:** Detects high-water mark timestamp lag (> 15 minutes) and row count divergences (> 0.1% delta) to prevent silent replication drop.

---

### 3.3 Tier 3: Change & Governance
Tier 3 ensures compliance, deployment integrity, and environment parity.
1. **`SetupAuditTrail` Direct-Production Sentinel:**
   - **Mechanism:** Continuous inspection of `SetupAuditTrail` on Alliance Production:
     ```sql
     SELECT Id, Action, Section, CreatedBy.Username, Display, CreatedDate 
     FROM SetupAuditTrail 
     WHERE CreatedDate = TODAY AND Action IN ('apexClass', 'apexTrigger', 'permSetAssign', 'vrDeactivate')
     ```
   - **Contract:** Detects out-of-band changes committed directly in Production outside the authorized CI/CD release pipeline.
2. **Cross-Org Metadata Drift:**
   - **Mechanism:** Compares cryptographic hashes and version signatures of Apex classes, trigger handlers, and record-triggered flows across Alliance Prod, TeamMD, and TeamHotfix.
   - **Contract:** Highlights un-backported hotfixes or configuration drift between staging and production.
3. **`ApexOrgWideCoverage` & Test Run Sentinel:**
   - **Mechanism:** Monitors org-wide code coverage and test runs:
     ```sql
     SELECT PercentCovered FROM ApexOrgWideCoverage
     ```
     ```sql
     SELECT Id, Status, ClassesEnqueued, ClassesCompleted, TestTime, IsAllTestsPass FROM ApexTestRunResult ORDER BY EndTime DESC LIMIT 5
     ```
   - **Contract:** Flags coverage drops below the 75.0% deployment threshold and alerts on regression test failures.
4. **`SandboxProcess` Staleness:**
   - **Mechanism:** Tracks sandbox copy freshness:
     ```sql
     SELECT Id, SandboxName, CopyProgress, StartDate, EndDate, Status FROM SandboxProcess ORDER BY EndDate DESC
     ```
   - **Contract:** Flags developer sandboxes older than 30 days and integration staging sandboxes older than 60 days without refresh.

---

### 3.4 Tier 4: Platform Hygiene & SLAs
Tier 4 tracks operational resource health and user experience metrics.
1. **`AuthSession` Active Users:**
   - **Mechanism:** Inspects concurrent active user sessions:
     ```sql
     SELECT Id, Users.Username, SessionType, LoginType, SourceIp, CreatedDate, LastModifiedDate 
     FROM AuthSession 
     WHERE SessionType = 'UI' AND LastModifiedDate = LAST_N_MINUTES:60
     ```
   - **Contract:** Gauges active user load, flags abnormal concurrent session spikes, and identifies idle session saturation.
2. **Storage Headroom Gauges:**
   - **Mechanism:** Queries `DataStorageMB` and `FileStorageMB` usage against org licensing caps.
   - **Contract:** Triggers warning at 80% capacity and critical alert at 95% capacity.
3. **Data Quality Null-Rate Probes:**
   - **Mechanism:** Executes statistical sampling on core operational fields:
     - `Encounter__c.Needs_Routing__c` null or stranded count.
     - `Denial_Lines__c.Claim_Amount__c` null rate.
     - `Contact.Email` null rate.
   - **Contract:** Detects upstream mapping failures if null rates deviate > 5% above historical baseline.
4. **Time-in-Queue SLAs:**
   - **Mechanism:** Calculates queue dwell duration:
     - `AsyncApexJob`: Difference between `CreatedDate` and first execution start.
     - `Encounter__c`: Duration stranded in `Needs_Routing__c = true`.
   - **Contract:** Flags SLA breach if batch queue dwell exceeds 10 minutes or encounter routing dwell exceeds 60 minutes.
5. **Salesforce Trust API Polling:**
   - **Mechanism:** Performs lightweight HTTPS GET queries against `https://api.status.salesforce.com/v1/instances/<INSTANCE>/status`.
   - **Contract:** Immediately indicates whether issues originate from Salesforce platform service disruptions (e.g. Major Incident / Maintenance) rather than internal codebase defects.

---

## 4. The Seven Platform Engineering Corrections

To eliminate performance degradation, race conditions, and governor limit traps, the system incorporates seven mandatory platform engineering corrections:

```
+────────────────────────────────────────────────────────────────────────────────────────────────────+
|                                7 PLATFORM ENGINEERING CORRECTIONS                                  |
+────────────────────────────────────────────────────────────────────────────────────────────────────+
| 1. AsyncApexJob Delta Velocity        : Compute batch execution velocity (jobs/min) vs static count|
| 2. FlexQueue Apex Execution           : Inspect 'Holding' queue status to prevent head-of-line clog|
| 3. CDC Entity Selection & commitUser  : Explicit entity channels & commitUser automated sync filter|
| 4. Child-Parent Lookup Cache          : In-memory LRU cache preventing N+1 SOQL lookup exhaustion  |
| 5. ReportEvent Exfiltration Sentinel  : Real-time export volume tracking on ReportEvent           |
| 6. Contact/Lead Email Bounces         : IsEmailBounced & EmailBouncedReason deliverability hygiene |
| 7. AuthSession Delta Polling          : Indexed timestamp filtering avoiding full table scans      |
+────────────────────────────────────────────────────────────────────────────────────────────────────+
```

### 4.1 Correction 1: `AsyncApexJob` Delta Velocity Tracking
- **Problem:** Static counts of completed batch jobs do not indicate whether batch pipelines are healthy or stalled. A batch that processed 10,000 records yesterday may appear "Processing" today while frozen in an infinite loop.
- **Correction:** The poller computes **Delta Execution Velocity** ($V = \frac{\Delta \text{JobItemsProcessed}}{\Delta t}$) between polling cycles. If a running job exhibits zero velocity ($V = 0$) across two consecutive polling intervals, Jarvis flags the batch as `STALLED_HEAD_OF_LINE` and notifies administrators.

### 4.2 Correction 2: `FlexQueue` Apex Execution Inspection
- **Problem:** Salesforce limits orgs to 5 concurrent running batches. Up to 100 additional batches are held in the `FlexQueue`. Standard queries only checking `Processing` miss jobs trapped in `Holding` status behind long-running behemoth jobs.
- **Correction:** Query `AsyncApexJob WHERE Status = 'Holding' ORDER BY JobType`. Jarvis displays holding queue depth and flags head-of-line blocking when high-priority sync jobs are delayed behind bulk recalculations.

### 4.3 Correction 3: CDC Entity Selection & `commitUser` Attribution
- **Problem:** Subscribing to wildcard Change Data Capture (`/data/ChangeEvents`) saturates event bus limits with noise. Furthermore, automated replication updates (e.g. MuleSoft/Snowflake writing back sync keys) trigger false-positive alert cascades.
- **Correction:**
  1. Restrict subscriptions to specific entity channels (e.g. `/data/Encounter__ChangeEvent`, `/data/Denial_Lines__ChangeEvent`).
  2. Inspect the `commitUser` header field. If `commitUser` matches known integration service accounts, suppress human-governance alerts and classify as automated sync activity.

### 4.4 Correction 4: Child-Parent Lookup Cache
- **Problem:** Evaluating stranded encounters or denial lines frequently requires traversing parent accounts, providers, or contracts. Repeatedly executing individual SOQL queries creates an $N+1$ query pattern that breaches the 100-SOQL governor limit.
- **Correction:** Implement a thread-safe, memory-bounded LRU Lookup Cache (`app/cache.py` / `ChildParentLookupCache`) in memory. Lookups for parent account IDs, billing provider profiles, and contract terms are resolved against the in-memory cache first with 15-minute TTL, reducing SOQL consumption by > 90%.

### 4.5 Correction 5: `ReportEvent` Exfiltration Sentinel
- **Problem:** High-volume data exfiltration often occurs via report exports rather than API calls.
- **Correction:** Monitor standard `ReportEvent` records (`WHERE Operation = 'ReportExported'`). Jarvis tracks records exported per user per hour and triggers an immediate high-priority alert if single-user export volume exceeds 25,000 records.

### 4.6 Correction 6: Contact/Lead Email Bounces
- **Problem:** Invalid email addresses produce high bounce rates that damage the org's sender IP reputation and cause critical patient billing notifications to fail.
- **Correction:** Query `IsEmailBounced` and `EmailBouncedReason` on `Contact` and `Lead`. Aggregate daily bounce counts and alert if daily bounce rate exceeds 2.5% of outbound messages.

### 4.7 Correction 7: `AuthSession` Delta Polling
- **Problem:** Unconstrained `SELECT ... FROM AuthSession` queries force full table scans across all historical session tokens, causing SOQL query timeouts and CPU spikes.
- **Correction:** Enforce indexed timestamp bounds on all session queries:
  ```sql
  SELECT Id, Users.Username, SessionType, SourceIp, CreatedDate, LastModifiedDate 
  FROM AuthSession 
  WHERE SessionType = 'UI' AND LastModifiedDate >= :last_poll_timestamp
  ```
  This restricts query cost to zero table scans and preserves database buffer caches.

---

## 5. Thread Contract & Inter-Module Communication

Thread safety across all Jarvis subsystems is strictly managed through `app/event_bus.py`.

### 5.1 Event Topics
The system utilizes standardized `EventTopic` enumeration values:

| Topic Enum | String Key | Payload Schema | Description |
|---|---|---|---|
| `SCAN_STARTED` | `scan_started` | `{"timestamp": float}` | Emitted when Poller begins a cycle |
| `SCAN_COMPLETED` | `scan_completed` | `TelemetrySnapshot` dict | Emitted when full 4-tier telemetry is assembled |
| `ORG_STATUS` | `org_status` | `OrgStatus` dataclass/dict | Emitted when org connectivity changes |
| `TIER1_ALERT` | `tier1_alert` | `{"error_type": str, "message": str, "source": str}` | Real-time batch/flow failure alert |
| `TIER2_ALERT` | `tier2_alert` | `{"integration": str, "status": str, "lag_sec": int}` | Integration or token expiry warning |
| `TIER3_ALERT` | `tier3_alert` | `{"action": str, "user": str, "details": str}` | Governance / direct-prod change alert |
| `TIER4_ALERT` | `tier4_alert` | `{"metric": str, "usage_pct": float}` | Hygiene / capacity / SLA breach warning |
| `VOICE_SPEAK` | `voice_speak` | `VoiceMessage` dataclass | Requests VoiceEngine to synthesize text |
| `VOICE_MUTE` | `voice_mute` | `{"muted": bool}` | Toggles global audio mute |
| `HUD_TOGGLE` | `hud_toggle` | `{"visible": bool}` | Requests HUD window toggle |
| `TRIGGER_SCAN` | `trigger_scan` | `{}` | Requests immediate Poller scan |
| `TRIGGER_BRIEFING`| `trigger_briefing`| `{}` | Requests immediate morning briefing |
| `SYSTEM_SHUTDOWN`| `system_shutdown`| `{}` | Coordinates clean application shutdown |

### 5.2 Threading Topology & Locks
- **Main Supervisor Thread:** Coordinates startup, watchdog, and shutdown.
- **Tray Daemon Thread:** Runs isolated `pystray` icon event loop.
- **Salesforce Poller Thread:** Runs scheduled queries; isolated by `threading.RLock()`.
- **HUD Server Thread:** Runs `uvicorn` / `asyncio` server for desktop cockpit.
- **Voice Worker Thread:** Background queue consumer; isolates audio synthesis and playback.

---

## 6. Comprehensive Telemetry Snapshot JSON Schema

The Poller produces a unified JSON dictionary persisted atomically to `app/state.json` and `app/telemetry_cache.json`:

```json
{
  "timestamp": 1727891200.0,
  "formatted_time": "2026-10-02 20:25:00",
  "system_state": "NOMINAL",
  "org_name": "Alliance Prod",
  "username": "admin@alliancehealth.org",
  "connected": true,
  "last_poll_time": 1727891200.0,
  "orgs": {
    "alliance_prod": {
      "alias": "Alliance Prod",
      "status": "Connected",
      "connected": true,
      "username": "admin@alliancehealth.org",
      "api_usage_percent": 14.2,
      "error": null
    },
    "team_md": {
      "alias": "TeamMD",
      "status": "Connected",
      "connected": true,
      "username": "integrations@teammd.org",
      "api_usage_percent": 8.5,
      "error": null
    },
    "team_hotfix": {
      "alias": "TeamHotfix",
      "status": "Connected",
      "connected": true,
      "username": "dev@teamhotfix.com",
      "api_usage_percent": 3.1,
      "error": null
    }
  },
  "tier1_realtime_failures": {
    "status": "NOMINAL",
    "batch_errors": [],
    "flow_execution_errors": [],
    "paused_flow_interviews": 0,
    "cron_trigger_blocked_jobs": 0,
    "unexpected_exceptions_count": 0
  },
  "tier2_integration_attribution": {
    "status": "NOMINAL",
    "bulk_api_active_jobs": 0,
    "bulk_api_failed_records": 0,
    "top_api_consumers": [
      {"app": "MuleSoft_Integration", "usage_pct": 12.1},
      {"app": "Snowflake_Replication", "usage_pct": 8.4}
    ],
    "certificate_expiry_warnings": [],
    "oauth_token_status": "VALID",
    "snowflake_reconciliation": {
      "status": "SYNCHRONIZED",
      "salesforce_row_count": 1420500,
      "snowflake_row_count": 1420500,
      "max_system_modstamp_lag_sec": 42
    }
  },
  "tier3_governance_change": {
    "status": "NOMINAL",
    "direct_prod_audit_events": 0,
    "metadata_drift_detected": false,
    "apex_code_coverage_pct": 84.6,
    "code_coverage_status": "PASS",
    "failed_test_classes_count": 0,
    "stale_sandboxes_count": 0
  },
  "tier4_platform_hygiene": {
    "status": "NOMINAL",
    "active_ui_sessions": 34,
    "data_storage_pct": 58.2,
    "file_storage_pct": 41.5,
    "field_null_rate_probes": {
      "encounter_needs_routing_pct": 0.05,
      "claim_amount_null_pct": 0.0
    },
    "queue_sla_breaches": 0,
    "salesforce_trust_status": "AVAILABLE"
  },
  "engineering_corrections": {
    "async_apex_delta_velocity": {"status": "OPTIMAL", "jobs_per_min": 14.2},
    "flex_queue_depth": 0,
    "cdc_entity_filtering": "ACTIVE",
    "child_parent_cache_hit_rate": 94.8,
    "report_export_events_count": 1,
    "email_bounce_rate_pct": 0.4,
    "auth_session_delta_polling": "INDEXED"
  },
  "batches": {
    "YesterdayDenialSyncBatch": {
      "name": "YesterdayDenialSyncBatch",
      "status": "Completed",
      "completed_time": "02:00 AM",
      "errors": 0,
      "total_processed": 1420,
      "total_batches": 12,
      "failed_batches": 0,
      "extended_status": null,
      "id": "707UP00002kupM5YAI"
    },
    "UpdateEncounterOwnerAndRoutingBatch": {
      "name": "UpdateEncounterOwnerAndRoutingBatch",
      "status": "Completed",
      "completed_time": "03:15 AM",
      "errors": 0,
      "total_processed": 3850,
      "total_batches": 18,
      "failed_batches": 0,
      "extended_status": null,
      "id": "707UP00002kugPoYAI"
    },
    "EncounterMemberIdBatch": {
      "name": "EncounterMemberIdBatch",
      "status": "Completed",
      "completed_time": "04:30 AM",
      "errors": 0,
      "total_processed": 1000,
      "total_batches": 8,
      "failed_batches": 0,
      "extended_status": null,
      "id": "707UP00002kunP9YAI"
    }
  },
  "batch_list": [
    {
      "name": "YesterdayDenialSyncBatch",
      "status": "Completed",
      "completed_time": "02:00 AM",
      "errors": 0,
      "total_processed": 1420,
      "total_batches": 12,
      "failed_batches": 0,
      "extended_status": null,
      "id": "707UP00002kupM5YAI"
    },
    {
      "name": "UpdateEncounterOwnerAndRoutingBatch",
      "status": "Completed",
      "completed_time": "03:15 AM",
      "errors": 0,
      "total_processed": 3850,
      "total_batches": 18,
      "failed_batches": 0,
      "extended_status": null,
      "id": "707UP00002kugPoYAI"
    },
    {
      "name": "EncounterMemberIdBatch",
      "status": "Completed",
      "completed_time": "04:30 AM",
      "errors": 0,
      "total_processed": 1000,
      "total_batches": 8,
      "failed_batches": 0,
      "extended_status": null,
      "id": "707UP00002kunP9YAI"
    }
  ],
  "metrics": {
    "stranded_encounters": 0,
    "daily_denials": 42,
    "yesterday_denial_claim_amount": 23938325.04,
    "yesterday_denial_charge_amount": 5132015.04,
    "today_denial_claim_amount": 17095403.04,
    "today_charge_amount": 5585153.04,
    "critical_conflicts": 0,
    "warning_conflicts": 0
  },
  "revenue": {
    "status": "nominal",
    "amount": 4120500,
    "formatted": "$4,120,500",
    "daily_target_pct": 103.4
  },
  "radar_summary": {
    "total_conflicts": 0,
    "critical_count": 0,
    "warning_count": 0,
    "is_clean": true
  },
  "governor_limits": {
    "daily_api_requests_max": 361000,
    "daily_api_requests_remaining": 267507,
    "daily_api_requests_used": 93493,
    "daily_api_requests_pct": 25.9,
    "daily_async_apex_max": 341000,
    "daily_async_apex_remaining": 244970,
    "daily_async_apex_used": 96030,
    "daily_async_apex_headroom_pct": 71.8,
    "apex_cpu_usage_pct": 22.0,
    "soql_query_usage_pct": 14.0
  }
}
```

---

## 7. Resource Budget & Zero-Window Guarantee

### 7.1 Memory Footprint (< 75.0 MB Working Set RAM)
- Total process Working Set RAM must remain strictly under 75.0 MB.
- Background poller sleeps between cycles and caches responses in memory/disk.
- Periodic `trim_working_set()` invokes `gc.collect()` and Windows API `EmptyWorkingSet`.
- Voice engine generates audio to temp files and streams playback asynchronously without heavy in-memory arrays.
- Memory watchdog in `app/main.py` logs memory usage periodically and warns if memory exceeds 75.0 MB.

### 7.2 Zero Console Window Guarantee
- Applications are invoked with `pythonw.exe` or detached process wrappers (`launch_jarvis_silent.vbs`).
- All `subprocess` calls MUST specify:
  ```python
  import subprocess
  CREATE_NO_WINDOW = 0x08000000
  # Usage: subprocess.run(cmd, creationflags=CREATE_NO_WINDOW, ...)
  ```

---

## 8. Unified Entrypoint Specification (`app/main.py`)

The supervisor `app/main.py` performs:
1. Argument parsing (`--mock`, `--no-voice`, `--headless`, `--test-boot`, `--interval`, `--port`).
2. Initialization of `EventBus`.
3. Startup registration verification (`app/startup.py`).
4. Instantiation of `SalesforcePoller`, `VoiceEngine`, `DesktopHUD`, and `JarvisTrayDaemon`.
5. Wiring of event bus subscriptions:
   - Poller telemetry -> HUD display & Tray icon status update.
   - Critical failures -> Toast notification (`app/notify.py`) + Voice alert.
   - Tray / HUD commands -> Poller rescan, Voice briefing, HUD toggle.
6. Execution of the background event / tray loop.
7. Graceful teardown on termination (SIGINT / Exit menu).
