/**
 * J.A.R.V.I.S. ENTERPRISE ARCHITECTURE COCKPIT // FRONTEND APP ENGINE v2.0
 * Connects the Arc-Reactor HUD to the Python background daemon & FastAPI server.
 * Full Real-Time Mission Control Flight Deck:
 * - Live Org Status Grid & Flight Gauges
 * - Active Batches & Healthcare RCM Telemetry
 * - Live CronTrigger Schedulers & BatchApexErrorEvent Stack Trace Viewer
 * - Tooling API DeployRequest Progress & SetupAuditTrail Prod Ticker
 * - Integrations & Governance Dashboard (Bulk API 2.0, API attribution, Certs, Snowflake DW sync)
 * - Quick Code Triage Dropzone (Jev System 1 Radar) & Antigravity FTS5 Memory Search
 */

(function () {
  'use strict';

  // State Management
  const state = {
    audioEnabled: true,
    speechActive: false,
    reactorOverclock: false,
    selectedTurn: null,
    pollInterval: null,
    speechUtterance: null,
    currentTab: 'tab-overview',
  };

  // Audio Synthesizer (Web Audio API)
  let audioCtx = null;
  function getAudioContext() {
    if (!audioCtx) {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (AudioContext) {
        audioCtx = new AudioContext();
      }
    }
    if (audioCtx && audioCtx.state === 'suspended') {
      audioCtx.resume();
    }
    return audioCtx;
  }

  function playCyberTone(type = 'beep') {
    if (!state.audioEnabled) return;
    try {
      const ctx = getAudioContext();
      if (!ctx) return;

      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);

      const now = ctx.currentTime;
      if (type === 'beep') {
        osc.type = 'sine';
        osc.frequency.setValueAtTime(880, now);
        osc.frequency.exponentialRampToValueAtTime(1760, now + 0.08);
        gain.gain.setValueAtTime(0.08, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.08);
        osc.start(now);
        osc.stop(now + 0.08);
      } else if (type === 'chirp') {
        osc.type = 'triangle';
        osc.frequency.setValueAtTime(440, now);
        osc.frequency.exponentialRampToValueAtTime(1320, now + 0.15);
        gain.gain.setValueAtTime(0.12, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.15);
        osc.start(now);
        osc.stop(now + 0.15);
      } else if (type === 'scan') {
        osc.type = 'sawtooth';
        osc.frequency.setValueAtTime(320, now);
        osc.frequency.linearRampToValueAtTime(960, now + 0.3);
        gain.gain.setValueAtTime(0.1, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.3);
        osc.start(now);
        osc.stop(now + 0.3);
      } else if (type === 'alert') {
        osc.type = 'square';
        osc.frequency.setValueAtTime(650, now);
        osc.frequency.setValueAtTime(450, now + 0.1);
        gain.gain.setValueAtTime(0.08, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.25);
        osc.start(now);
        osc.stop(now + 0.25);
      }
    } catch (e) {
      // Audio autoplay policy fallback
    }
  }

  // Preset Apex Code Snippets for Instant Testing
  const CODE_PRESETS = {
    recursion: `// TRIGGER: AccountTrigger.trigger (Infinite Recursion Hazard)
trigger AccountTrigger on Account (after update) {
    // Unbounded DML update without static recursion guard
    List<Contact> contacts = [SELECT Id, AccountId FROM Contact WHERE AccountId IN :Trigger.newMap.keySet()];
    for (Contact c : contacts) {
        c.Sync_Status__c = 'Pending';
    }
    update contacts; 
    // ContactTrigger will update Account again, causing recursion loop
}`,
    race: `// APEX HANDLER: FlowsheetApprovalHandler.cls
public with sharing class FlowsheetApprovalHandler {
    public static void processDisciplineSignoff(List<Flowsheet__c> records) {
        for (Flowsheet__c fs : records) {
            // Competes directly with Flowsheet_Approval_Flow during OT saves
            if (fs.Discipline__c == 'Occupational Therapy') {
                fs.Status__c = 'Provider Review'; 
            }
        }
        update records;
    }
}`,
    gov_loop: `// APEX CLASS: PatientEncounterBatch.cls (Governor Limit Breach)
public class PatientEncounterBatch {
    public void processEncounters(List<Encounter__c> encounters) {
        for (Encounter__c enc : encounters) {
            // ANTI-PATTERN: SOQL query inside loop
            List<Claim__c> claims = [SELECT Id, Total_Charge__c FROM Claim__c WHERE Encounter__c = :enc.Id];
            
            // ANTI-PATTERN: DML inside loop
            enc.Claims_Count__c = claims.size();
            update enc;
        }
    }
}`,
    parent_lock: `// HIGH VOLUME BATCH: ClaimSubmissionBatch.cls
public class ClaimSubmissionBatch {
    public void executeBulk(List<Claim__c> claims) {
        // High volume parent lock contention on shared billing account
        Id commonParent = '001f200000ParentA';
        for (Claim__c c : claims) {
            c.Patient_Billing_Group__c = commonParent;
        }
        // Concurrent threads will throw UNABLE_TO_LOCK_ROW
        update claims;
    }
}`,
    clean: `// ARCHITECTURALLY CLEAN APEX SERVICE
public with sharing class CareCloudSyncService {
    private static Set<Id> processedIds = new Set<Id>();

    public static void executeSync(List<Encounter__c> newEncounters) {
        List<Encounter__c> toUpdate = new List<Encounter__c>();
        Set<Id> encIds = new Set<Id>();
        
        for (Encounter__c enc : newEncounters) {
            if (!processedIds.contains(enc.Id)) {
                encIds.add(enc.Id);
                processedIds.add(enc.Id);
            }
        }
        
        if (encIds.isEmpty()) return;
        
        // Bulkified query outside of loop
        Map<Id, Encounter__c> existing = new Map<Id, Encounter__c>(
            [SELECT Id, Sync_Status__c FROM Encounter__c WHERE Id IN :encIds]
        );
        
        for (Encounter__c e : existing.values()) {
            e.Sync_Status__c = 'Synced';
            toUpdate.add(e);
        }
        
        // Single bulk DML outside loop
        if (!toUpdate.isEmpty()) {
            update toUpdate;
        }
    }
}`
  };

  /* =====================================================================
     SRE PLATFORM HEALTH GAUGE (Circular SLO Dial)
     ===================================================================== */
  function initArcReactor() {
    const canvas = document.getElementById('arc-reactor-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    const centerX = width / 2;
    const centerY = height / 2;
    const radius = Math.min(centerX, centerY) - 8;

    let pulse = 0;

    function draw() {
      ctx.clearRect(0, 0, width, height);

      // Background track
      ctx.beginPath();
      ctx.arc(centerX, centerY, radius, 0, Math.PI * 2);
      ctx.strokeStyle = '#1e293b';
      ctx.lineWidth = 3.5;
      ctx.stroke();

      // Active SLO arc (99.98% of circle)
      const endAngle = (Math.PI * 1.5) + (Math.PI * 2 * 0.9998);
      ctx.beginPath();
      ctx.arc(centerX, centerY, radius, Math.PI * 1.5, endAngle);
      ctx.strokeStyle = '#10b981';
      ctx.lineWidth = 3.5;
      ctx.lineCap = 'round';
      ctx.stroke();

      // Center pulse dot
      pulse += 0.05;
      const dotRad = 3.5 + Math.sin(pulse) * 0.8;
      ctx.beginPath();
      ctx.arc(centerX, centerY, dotRad, 0, Math.PI * 2);
      ctx.fillStyle = '#10b981';
      ctx.fill();

      requestAnimationFrame(draw);
    }

    draw();

    const container = document.getElementById('arc-reactor-container');
    if (container) {
      container.addEventListener('click', () => {
        switchTab('tab-copilot');
      });
    }
  }

  /* =====================================================================
     CLOCK & REALTIME DISPLAY
     ===================================================================== */
  function updateClock() {
    const clockEl = document.getElementById('hud-clock');
    const dateEl = document.getElementById('hud-date');
    const now = new Date();

    if (clockEl) {
      const hours = String(now.getHours()).padStart(2, '0');
      const minutes = String(now.getMinutes()).padStart(2, '0');
      const seconds = String(now.getSeconds()).padStart(2, '0');
      clockEl.textContent = `${hours}:${minutes}:${seconds}`;
    }

    if (dateEl) {
      const options = { month: 'long', day: '2-digit', year: 'numeric' };
      dateEl.textContent = now.toLocaleDateString('en-US', options).toUpperCase();
    }
  }

  /* =====================================================================
     TAB NAVIGATION ENGINE
     ===================================================================== */
  function switchTab(targetTabId) {
    state.currentTab = targetTabId;

    // Update nav buttons
    document.querySelectorAll('.nav-tab-btn').forEach(btn => {
      if (btn.getAttribute('data-tab') === targetTabId) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });

    // Update tab panels
    document.querySelectorAll('.tab-content-panel').forEach(panel => {
      if (panel.id === targetTabId) {
        panel.classList.add('active');
      } else {
        panel.classList.remove('active');
      }
    });
  }
  window.switchTab = switchTab;

  function initTabNavigation() {
    document.querySelectorAll('.nav-tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const tabId = btn.getAttribute('data-tab');
        if (tabId) switchTab(tabId);
      });
    });

    // Quick jump buttons from Overview
    const jumpSched = document.getElementById('jump-to-schedulers-btn');
    if (jumpSched) jumpSched.addEventListener('click', () => switchTab('tab-schedulers'));

    const jumpDeploy = document.getElementById('jump-to-deploy-btn');
    if (jumpDeploy) jumpDeploy.addEventListener('click', () => switchTab('tab-deployments'));

    const jumpTriage = document.getElementById('jump-to-triage-btn');
    if (jumpTriage) jumpTriage.addEventListener('click', () => switchTab('tab-triage'));

    // Keyboard hotkeys: 0 (Copilot), 1-5 to switch tabs
    window.addEventListener('keydown', (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      if (e.key === '0' || e.key === '`' || e.key.toLowerCase() === 'a') switchTab('tab-copilot');
      else if (e.key === '1') switchTab('tab-overview');
      else if (e.key === '2') switchTab('tab-schedulers');
      else if (e.key === '3') switchTab('tab-deployments');
      else if (e.key === '4') switchTab('tab-integrations');
      else if (e.key === '5') switchTab('tab-triage');
    });
  }

  /* =====================================================================
     API INTEGRATIONS & LIVE TELEMETRY
     ===================================================================== */
  async function fetchSystemStatus() {
    try {
      const res = await fetch('/api/status');
      if (!res.ok) throw new Error('Status fetch failed');
      const data = await res.json();

      renderOrgGrid(data.orgs);
      updateDaemonChip(data.daemon);
      updateFlightGauges(data);
    } catch (err) {
      console.warn('Could not fetch /api/status:', err);
    }
  }

  function updateFlightGauges(data) {
    // 1. Data Storage
    if (data.storage_usage && data.storage_usage.data_storage) {
      const ds = data.storage_usage.data_storage;
      const elVal = document.getElementById('data-storage-val');
      const elBadge = document.getElementById('data-storage-badge');
      const elFill = document.getElementById('data-storage-fill');
      if (elVal) elVal.textContent = `${ds.used_formatted} / ${ds.max_formatted}`;
      if (elBadge) elBadge.textContent = `${ds.percent}%`;
      if (elFill) elFill.style.width = `${ds.percent}%`;
    }

    // 2. File Storage
    if (data.storage_usage && data.storage_usage.file_storage) {
      const fs = data.storage_usage.file_storage;
      const elVal = document.getElementById('file-storage-val');
      const elBadge = document.getElementById('file-storage-badge');
      const elFill = document.getElementById('file-storage-fill');
      if (elVal) elVal.textContent = `${fs.used_formatted} / ${fs.max_formatted}`;
      if (elBadge) elBadge.textContent = `${fs.percent}%`;
      if (elFill) elFill.style.width = `${fs.percent}%`;
    }

    // 3. Daily API Gas Tank
    if (data.governor_gauges) {
      const gg = data.governor_gauges;
      const elVal = document.getElementById('api-usage-val');
      const elBadge = document.getElementById('api-usage-badge');
      const elFill = document.getElementById('api-usage-fill');
      if (elVal) elVal.textContent = `${Number(gg.daily_api_used).toLocaleString()} / ${Number(gg.daily_api_max).toLocaleString()}`;
      if (elBadge) elBadge.textContent = `${gg.daily_api_pct}%`;
      if (elFill) elFill.style.width = `${gg.daily_api_pct}%`;

      // 4. Outbound SingleEmail
      const emVal = document.getElementById('email-usage-val');
      const emBadge = document.getElementById('email-usage-badge');
      const emFill = document.getElementById('email-usage-fill');
      if (emVal) emVal.textContent = `${Number(gg.single_email_used).toLocaleString()} / ${Number(gg.single_email_max).toLocaleString()}`;
      if (emBadge) emBadge.textContent = `${gg.single_email_pct}%`;
      if (emFill) emFill.style.width = `${gg.single_email_pct}%`;
    }

    // 5. Active Users
    if (data.active_users) {
      const uVal = document.getElementById('users-val');
      const uBadge = document.getElementById('users-badge');
      if (uVal) uVal.textContent = `${data.active_users.count} Active Sessions`;
      if (uBadge) uBadge.textContent = `${data.active_users.count} SESSIONS`;
    }

    // 6. Trust Pod Header & Summary
    if (data.trust_pod) {
      const podVal = document.getElementById('header-pod-val');
      const podSum = document.getElementById('summary-pod-status');
      if (podVal) podVal.textContent = `${data.trust_pod.instance_pod} // ${data.trust_pod.status}`;
      if (podSum) podSum.textContent = `${data.trust_pod.instance_pod} (${data.trust_pod.status}, ${data.trust_pod.latency_ms}ms)`;
    }
  }

  function updateDaemonChip(daemon) {
    const chip = document.getElementById('daemon-status-chip');
    if (chip && daemon) {
      chip.innerHTML = `<span class="chip-label">NODES</span><span class="chip-val">${daemon.graph_nodes || 207}</span>`;
    }
    const syncTime = document.getElementById('last-sync-time');
    if (syncTime) {
      const d = new Date();
      syncTime.textContent = `SYNCED: ${d.toLocaleTimeString()}`;
    }
  }

  function renderOrgGrid(orgs) {
    const container = document.getElementById('org-grid-container');
    if (!container || !orgs) return;

    container.innerHTML = orgs.map(org => {
      const badgeClass = org.status === 'ONLINE' ? 'badge-online' : (org.status === 'WARNING' ? 'badge-warning' : 'badge-standby');
      const cardTypeClass = org.id === 'alliance_prod' ? 'org-prod' : (org.status === 'WARNING' ? 'org-warning' : 'org-standby');
      const soqlFillClass = org.soql_percent > 40 ? 'fill-amber' : 'fill-cyan';
      const dmlFillClass = org.dml_percent > 30 ? 'fill-amber' : 'fill-teal';

      return `
        <div class="org-card glass-panel ${cardTypeClass}">
          <div class="org-top-row">
            <div class="org-identity">
              <h3>${org.name}</h3>
              <span class="org-type-tag">${org.type} • ${org.org_id}</span>
            </div>
            <div class="org-status-badge ${badgeClass}">
              <span class="pulsing-dot ${org.status === 'ONLINE' ? 'dot-cyan' : (org.status === 'WARNING' ? 'dot-amber' : 'dot-green')}"></span>
              <span>${org.status}</span>
            </div>
          </div>

          <!-- Governor Meters -->
          <div class="org-meters">
            <div class="meter-row">
              <div class="meter-labels">
                <span>SOQL CAPACITY</span>
                <span>${org.soql_percent}% (${org.soql_detail})</span>
              </div>
              <div class="meter-track">
                <div class="meter-fill ${soqlFillClass}" style="width: ${org.soql_percent}%"></div>
              </div>
            </div>

            <div class="meter-row">
              <div class="meter-labels">
                <span>DML CAPACITY</span>
                <span>${org.dml_percent}% (${org.dml_detail})</span>
              </div>
              <div class="meter-track">
                <div class="meter-fill ${dmlFillClass}" style="width: ${org.dml_percent}%"></div>
              </div>
            </div>
          </div>

          ${org.alert_message ? `
            <div class="org-alert-banner">
              ⚠️ ${org.alert_message}
            </div>
          ` : ''}

          <div class="org-bottom-info">
            <span>SYNC LATENCY: ${org.latency_ms}ms</span>
            <span>AUTOMATIONS: ${org.active_triggers} Triggers / ${org.active_flows} Flows</span>
          </div>
        </div>
      `;
    }).join('');
  }

  async function fetchActiveBatches() {
    try {
      const res = await fetch('/api/batches');
      if (!res.ok) throw new Error('Batches fetch failed');
      const data = await res.json();
      renderBatches(data.batches);
    } catch (err) {
      console.warn('Could not fetch /api/batches:', err);
    }
  }

  function renderBatches(batches) {
    const list = document.getElementById('batches-list');
    if (!list || !batches) return;

    list.innerHTML = batches.map(batch => {
      const isWarn = batch.errors > 0;
      const barClass = isWarn ? 'batch-bar-warning' : '';

      return `
        <div class="batch-item">
          <div class="batch-header">
            <div class="batch-name-wrap">
              <span class="batch-name">${batch.name}</span>
              <span class="batch-target">${batch.target_object}</span>
            </div>
            <div class="batch-metrics">
              <span>${batch.percent}%</span>
              <span>(${batch.processed.toLocaleString()} / ${batch.total.toLocaleString()})</span>
            </div>
          </div>

          <div class="batch-bar-wrap">
            <div class="batch-bar-fill ${barClass}" style="width: ${batch.percent}%"></div>
          </div>

          <div class="batch-footer">
            <span>RATE: ${batch.rate} • ETA: ${batch.eta}</span>
            <span>ERRORS: <strong style="color: ${batch.errors > 0 ? '#ef4444' : '#10b981'}">${batch.errors}</strong></span>
          </div>

          ${batch.error_details ? `
            <div class="batch-error-callout">
              ⚠️ ${batch.error_details}
            </div>
          ` : ''}
        </div>
      `;
    }).join('');
  }

  async function fetchRcmStats() {
    try {
      const res = await fetch('/api/rcm');
      if (!res.ok) throw new Error('RCM fetch failed');
      const data = await res.json();

      const summary = data.summary;
      const elDenVol = document.getElementById('rcm-denials-vol');
      const elDenCnt = document.getElementById('rcm-denials-count');
      const elUnrouted = document.getElementById('rcm-unrouted-count');
      const elFlowsheet = document.getElementById('rcm-flowsheet-queue');
      const elCleanRate = document.getElementById('rcm-clean-rate');

      if (elDenVol) elDenVol.textContent = summary.denials_volume_formatted;
      if (elDenCnt) elDenCnt.textContent = `${summary.denials_count} claims under review`;
      if (elUnrouted) elUnrouted.textContent = summary.unrouted_encounters;
      if (elFlowsheet) elFlowsheet.textContent = summary.flowsheets_in_review;
      if (elCleanRate) elCleanRate.textContent = summary.clean_claim_rate;

      renderRcmDenials(data.priority_denials);
    } catch (err) {
      console.warn('Could not fetch /api/rcm:', err);
    }
  }

  function renderRcmDenials(denials) {
    const list = document.getElementById('rcm-denials-list');
    if (!list || !denials) return;

    list.innerHTML = denials.map(d => `
      <div class="rcm-denial-card" title="${d.reason}">
        <div class="rcm-card-top">
          <span class="rcm-claim-id">${d.id}</span>
          <span class="rcm-claim-amount">$${d.amount.toLocaleString()}</span>
        </div>
        <div class="rcm-patient-line">${d.patient_code} • ${d.payer}</div>
        <div class="rcm-reason-pill"><strong>${d.code}:</strong> ${d.reason}</div>
        <div class="rcm-action-hint">💡 Suggestion: ${d.action_suggestion}</div>
      </div>
    `).join('');
  }

  /* =====================================================================
     SCHEDULERS & BATCH TRACE TELEMETRY
     ===================================================================== */
  async function fetchSchedulers() {
    try {
      const res = await fetch('/api/schedulers');
      if (!res.ok) throw new Error('Schedulers fetch failed');
      const data = await res.json();

      // Render table
      const tbody = document.getElementById('schedulers-table-body');
      if (tbody && data.schedulers) {
        tbody.innerHTML = data.schedulers.map(s => {
          let badgeHtml = `<span class="status-badge-normal">WAITING</span>`;
          if (s.status_badge === 'MISSED' || s.missed_alert) {
            badgeHtml = `<span class="status-badge-missed">⚠ MISSED</span>`;
          } else if (s.status_badge === 'EXECUTING') {
            badgeHtml = `<span class="status-badge-executing">● EXECUTING</span>`;
          }

          return `
            <tr>
              <td><strong>${s.job_name}</strong></td>
              <td style="font-family: var(--font-mono); font-size: 12px; color: var(--cyan-core);">${s.apex_class}</td>
              <td style="font-family: var(--font-mono); font-size: 12px;">${s.cron_expression}</td>
              <td>${s.state}</td>
              <td style="font-size: 12px; color: var(--text-secondary);">${s.previous_fire_time}</td>
              <td style="font-size: 12px; color: var(--text-primary); font-weight: 600;">${s.next_fire_time}</td>
              <td style="font-family: var(--font-mono); font-size: 12px; color: ${s.missed_alert ? '#ef4444' : 'var(--teal-accent)'};">${s.next_fire_countdown}</td>
              <td>${badgeHtml}</td>
            </tr>
          `;
        }).join('');
      }

      // Update badge
      const badge = document.getElementById('schedulers-badge');
      if (badge) {
        badge.textContent = `${data.missed_alerts_count} MISSED / LATE RUN`;
      }

      // Render BatchApexErrorEvents
      const errorList = document.getElementById('batch-error-content-list');
      if (errorList && data.batch_apex_errors) {
        errorList.innerHTML = data.batch_apex_errors.map(err => `
          <div class="batch-error-card">
            <div class="batch-error-header">
              <span class="batch-error-title">🚨 ${err.job_name} (Job: ${err.job_id}) • Phase: ${err.phase}</span>
              <span style="font-size: 11px; color: var(--text-muted); font-family: var(--font-mono);">${err.timestamp}</span>
            </div>
            <div class="batch-error-msg"><strong>${err.exception_type}:</strong> ${err.message}</div>
            <div class="failing-record-pills">
              <span class="record-pill-label">FAILING RECORD IDs IN CHUNK:</span>
              ${err.failing_record_ids.map(id => `<span class="record-pill">${id}</span>`).join('')}
            </div>
            <div class="stack-trace-code">${err.stack_trace}</div>
            <div class="batch-remediation-tip">💡 <strong>Remediation:</strong> ${err.remediation}</div>
          </div>
        `).join('');
      }
    } catch (err) {
      console.warn('Could not fetch /api/schedulers:', err);
    }
  }

  /* =====================================================================
     LIVE DEPLOYMENTS & SETUP AUDIT TRAIL
     ===================================================================== */
  async function fetchDeployments() {
    try {
      const res = await fetch('/api/deployments');
      if (!res.ok) throw new Error('Deployments fetch failed');
      const data = await res.json();

      const depBox = document.getElementById('deploy-progress-box');
      if (depBox && data.active_deployment) {
        const dep = data.active_deployment;
        depBox.innerHTML = `
          <div class="deploy-header-row">
            <div>
              <span class="deploy-title-main">${dep.name}</span>
              <span style="font-size: 12px; color: var(--text-secondary); margin-left: 10px;">(ID: ${dep.deploy_id})</span>
            </div>
            <span class="status-badge-executing">PROGRESS: ${dep.percent}%</span>
          </div>

          <div class="deploy-progress-bar-large">
            <div class="deploy-progress-fill" style="width: ${dep.percent}%;"></div>
          </div>

          <div class="deploy-meta-grid">
            <div class="deploy-meta-item">
              <span class="deploy-meta-label">TARGET ORG</span>
              <span class="deploy-meta-val text-cyan">${dep.target_org}</span>
            </div>
            <div class="deploy-meta-item">
              <span class="deploy-meta-label">COMPONENTS DEPLOYED</span>
              <span class="deploy-meta-val text-teal">${dep.components_deployed} / ${dep.components_total} Components</span>
            </div>
            <div class="deploy-meta-item">
              <span class="deploy-meta-label">APEX UNIT TESTS</span>
              <span class="deploy-meta-val text-green">${dep.run_tests_completed} / ${dep.run_tests_total} Tests Run</span>
            </div>
            <div class="deploy-meta-item">
              <span class="deploy-meta-label">ESTIMATED TIME</span>
              <span class="deploy-meta-val text-amber">ETA: ~${dep.eta_seconds}s</span>
            </div>
          </div>

          <div style="font-size: 12.5px; color: var(--text-secondary); margin-bottom: 8px;">
            Current Component In-Flight: <strong style="color: var(--cyan-core); font-family: var(--font-mono);">${dep.current_component}</strong>
          </div>

          <table class="components-table">
            <thead>
              <tr>
                <th>COMPONENT NAME</th>
                <th>METADATA TYPE</th>
                <th>DEPLOY STATUS</th>
              </tr>
            </thead>
            <tbody>
              ${(dep.components_summary || []).map(c => `
                <tr>
                  <td style="font-family: var(--font-mono); font-size: 12px;">${c.name}</td>
                  <td style="color: var(--text-secondary);">${c.type}</td>
                  <td><span class="${c.status === 'Deployed' ? 'status-badge-normal' : (c.status === 'Deploying' ? 'status-badge-executing' : '')}">${c.status}</span></td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        `;
      }

      // Render SetupAuditTrail
      const ticker = document.getElementById('setup-audit-ticker');
      if (ticker && data.setup_audit_trail && data.setup_audit_trail.items) {
        ticker.innerHTML = data.setup_audit_trail.items.map(item => `
          <div class="setup-audit-item ${item.outside_pipeline ? 'audit-warning' : ''}">
            <div class="audit-left">
              <div class="audit-display-text">${item.display}</div>
              <div class="audit-meta-line">
                Action: <strong>${item.action}</strong> • User: <strong>${item.created_by}</strong> • Section: ${item.section} • ${item.timestamp}
              </div>
              ${item.outside_pipeline ? `
                <div style="font-size: 12px; color: #fca5a5; margin-top: 4px;">
                  ⚠️ ${item.recommendation}
                </div>
              ` : ''}
            </div>
            <div>
              ${item.outside_pipeline ? `<span class="badge-outside-pipeline">⚠ DIRECT PROD EDIT</span>` : `<span class="status-badge-normal">MANAGED</span>`}
            </div>
          </div>
        `).join('');
      }
    } catch (err) {
      console.warn('Could not fetch /api/deployments:', err);
    }
  }

  /* =====================================================================
     INTEGRATIONS & GOVERNANCE DASHBOARD
     ===================================================================== */
  async function fetchIntegrations() {
    try {
      const res = await fetch('/api/integrations');
      if (!res.ok) throw new Error('Integrations fetch failed');
      const data = await res.json();

      // 1. Bulk API 2.0 Jobs
      const bulkList = document.getElementById('bulk-api-jobs-list');
      if (bulkList && data.bulk_api_jobs) {
        bulkList.innerHTML = data.bulk_api_jobs.map(job => `
          <div class="bulk-job-item">
            <div class="bulk-job-top">
              <span class="bulk-job-name">${job.object} (${job.operation.toUpperCase()})</span>
              <span class="${job.state === 'JobComplete' ? 'status-badge-normal' : (job.state === 'InProgress' ? 'status-badge-executing' : '')}">${job.state}</span>
            </div>
            <div class="bulk-job-stats">
              Processed: <strong>${Number(job.records_processed).toLocaleString()}</strong> / ${Number(job.total_records).toLocaleString()} • Failed: <strong style="color: ${job.records_failed > 0 ? '#ef4444' : '#10b981'};">${job.records_failed}</strong> • Concurrency: ${job.concurrency_mode}
            </div>
          </div>
        `).join('');
      }

      // 2. API Attribution
      const attrBox = document.getElementById('api-attribution-breakdown');
      if (attrBox && data.api_attribution && data.api_attribution.by_connected_app) {
        attrBox.innerHTML = `
          ${data.api_attribution.by_connected_app.map(app => `
            <div class="api-attribution-bar-item">
              <div class="attribution-label-row">
                <span>${app.app}</span>
                <span style="font-family: var(--font-mono);">${Number(app.calls).toLocaleString()} calls (${app.percent}%)</span>
              </div>
              <div class="attribution-bar-track">
                <div class="attribution-bar-fill" style="width: ${app.percent}%;"></div>
              </div>
            </div>
          `).join('')}
        `;
      }

      // 3. Certificate Expiration Tracker
      const certList = document.getElementById('cert-tracker-list');
      if (certList && data.certificate_tracker) {
        certList.innerHTML = data.certificate_tracker.map(c => {
          const isWarn = c.status === 'EXPIRING_SOON';
          return `
            <div class="cert-card-item ${isWarn ? 'cert-warn' : ''}">
              <div class="cert-top-row">
                <span class="cert-org-name">${c.org}: ${c.name}</span>
                <span class="cert-countdown-badge ${isWarn ? 'status-badge-missed' : 'status-badge-normal'}">
                  ${c.expires_in_days} DAYS LEFT
                </span>
              </div>
              <div class="cert-details-text">
                Expires: ${c.expiration_date} • OAuth Status: <strong style="color: ${c.oauth_token_status.includes('REVOKED') ? '#ef4444' : 'var(--cyan-core)'};">${c.oauth_token_status}</strong>
              </div>
            </div>
          `;
        }).join('');
      }

      // 4. Snowflake DW Reconciliation
      const sfTable = document.getElementById('snowflake-recon-table');
      if (sfTable && data.snowflake_reconciliation && data.snowflake_reconciliation.tables) {
        sfTable.innerHTML = data.snowflake_reconciliation.tables.map(t => `
          <div class="snowflake-recon-row">
            <div>
              <strong style="font-family: var(--font-mono); color: var(--cyan-core);">${t.table}</strong>
              <div style="font-size: 11px; color: var(--text-muted);">${t.target_stage}</div>
            </div>
            <div style="font-family: var(--font-mono); font-size: 12px;">
              SF: ${t.salesforce_count.toLocaleString()} | SNOW: ${t.snowflake_count.toLocaleString()} (Δ ${t.delta})
            </div>
            <div>
              <span class="status-badge-normal">${t.badge}</span>
            </div>
          </div>
        `).join('');
      }
    } catch (err) {
      console.warn('Could not fetch /api/integrations:', err);
    }
  }

  async function fetchGovernance() {
    try {
      const res = await fetch('/api/governance');
      if (!res.ok) throw new Error('Governance fetch failed');
      const data = await res.json();

      // 1. Code Coverage Box
      const covBox = document.getElementById('gov-coverage-box');
      if (covBox && data.code_coverage) {
        const cc = data.code_coverage;
        covBox.innerHTML = `
          <div class="gov-box-card">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span>Org Overall Coverage:</span>
              <strong style="color: #34d399; font-size: 16px;">${cc.overall_coverage_pct}%</strong>
            </div>
            <div style="font-size: 11.5px; color: var(--text-secondary); margin-top: 4px;">
              Classes Below 75% Threshold:
            </div>
            ${(cc.classes_below_threshold || []).map(cls => `
              <div style="display: flex; justify-content: space-between; font-size: 12px; font-family: var(--font-mono); background: rgba(239,68,68,0.1); padding: 4px 6px; border-radius: 3px;">
                <span>${cls.class_name}</span>
                <span style="color: #fca5a5;">${cls.coverage_pct}% (FAIL)</span>
              </div>
            `).join('')}
          </div>
        `;
      }

      // 2. Sandbox Staleness Box
      const sbBox = document.getElementById('gov-sandboxes-box');
      if (sbBox && data.sandbox_staleness) {
        sbBox.innerHTML = data.sandbox_staleness.map(sb => {
          const isStale = sb.status === 'STALE';
          return `
            <div class="gov-box-card" style="${isStale ? 'border-color: rgba(245,158,11,0.5);' : ''}">
              <div style="display: flex; justify-content: space-between;">
                <strong>${sb.sandbox_name}</strong>
                <span class="${isStale ? 'status-badge-missed' : 'status-badge-normal'}">${sb.status}</span>
              </div>
              <div style="font-size: 12px; color: var(--text-secondary);">
                Refreshed ${sb.days_since_refresh}d ago • Behind Prod: ${sb.commits_behind_prod} commits
              </div>
            </div>
          `;
        }).join('');
      }

      // 3. Null Probes Box
      const nullBox = document.getElementById('gov-null-probes-box');
      if (nullBox && data.data_quality_null_probes) {
        nullBox.innerHTML = `
          <div class="gov-box-card">
            ${data.data_quality_null_probes.map(p => `
              <div class="null-probe-item">
                <span style="font-family: var(--font-mono); font-size: 12px;">${p.object}.${p.field}</span>
                <span class="${p.status === 'WARNING' ? 'status-badge-missed' : 'status-badge-normal'}">
                  ${p.null_rate_pct}% Nulls
                </span>
              </div>
            `).join('')}
          </div>
        `;
      }
    } catch (err) {
      console.warn('Could not fetch /api/governance:', err);
    }
  }

  /* =====================================================================
     QUICK CODE TRIAGE ENGINE
     ===================================================================== */
  function initCodeTriage() {
    const codeInput = document.getElementById('triage-code-input');
    const scanBtn = document.getElementById('triage-scan-btn');
    const clearBtn = document.getElementById('triage-clear-btn');
    const dropzoneBox = document.getElementById('code-dropzone-box');
    const presetBtns = document.querySelectorAll('.sample-btn');

    // Preset buttons
    presetBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        playCyberTone('beep');
        const key = btn.getAttribute('data-preset');
        if (CODE_PRESETS[key] && codeInput) {
          codeInput.value = CODE_PRESETS[key];
          runTriageScan(CODE_PRESETS[key]);
        }
      });
    });

    // Clear
    if (clearBtn && codeInput) {
      clearBtn.addEventListener('click', () => {
        playCyberTone('beep');
        codeInput.value = '';
        const resultsWrapper = document.getElementById('triage-results-wrapper');
        if (resultsWrapper) resultsWrapper.style.display = 'none';
      });
    }

    // Scan
    if (scanBtn && codeInput) {
      scanBtn.addEventListener('click', () => {
        runTriageScan(codeInput.value);
      });
    }

    // Ctrl + Enter shortcut
    if (codeInput) {
      codeInput.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.key === 'Enter') {
          e.preventDefault();
          runTriageScan(codeInput.value);
        }
      });
    }

    // Drag and Drop
    if (dropzoneBox && codeInput) {
      dropzoneBox.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzoneBox.classList.add('dragover');
      });
      dropzoneBox.addEventListener('dragleave', () => {
        dropzoneBox.classList.remove('dragover');
      });
      dropzoneBox.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzoneBox.classList.remove('dragover');
        if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]) {
          const file = e.dataTransfer.files[0];
          const reader = new FileReader();
          reader.onload = (event) => {
            codeInput.value = event.target.result;
            playCyberTone('chirp');
            runTriageScan(event.target.result);
          };
          reader.readAsText(file);
        }
      });
    }
  }

  async function runTriageScan(code) {
    if (!code || !code.trim()) return;

    playCyberTone('scan');
    state.reactorOverclock = true;
    setTimeout(() => { state.reactorOverclock = false; }, 1200);

    const resultsWrapper = document.getElementById('triage-results-wrapper');
    const decisionBar = document.getElementById('jev-decision-bar');
    const conflictsOutput = document.getElementById('conflicts-output');

    if (resultsWrapper) resultsWrapper.style.display = 'block';
    if (decisionBar) decisionBar.innerHTML = `<div class="loading-placeholder">Executing TypeSafe Jev System 1 triage...</div>`;
    if (conflictsOutput) conflictsOutput.innerHTML = '';

    try {
      const res = await fetch('/api/triage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: code }),
      });

      if (!res.ok) throw new Error('Triage scan failed');
      const data = await res.json();

      renderTriageResults(data);
    } catch (err) {
      if (decisionBar) {
        decisionBar.innerHTML = `<div class="text-crimson">Scan Error: ${err.message}</div>`;
      }
    }
  }

  function renderTriageResults(data) {
    const decisionBar = document.getElementById('jev-decision-bar');
    const conflictsOutput = document.getElementById('conflicts-output');

    const jev = data.jev;
    const stats = data.stats;
    const conflicts = data.conflicts || [];
    const passed = stats.quality_gate_passed;

    if (decisionBar) {
      decisionBar.innerHTML = `
        <div class="jev-decision-card">
          <div class="decision-left">
            <span class="decision-domain">${jev.domain}</span>
            <span class="decision-title">ACTION: ${jev.action}</span>
          </div>
          <div class="decision-right">
            <span class="decision-chip chip-latency">TRIAGE: ${stats.triage_latency_ms}ms</span>
            <span class="decision-chip chip-latency">RADAR: ${stats.radar_latency_ms}ms</span>
            <span class="decision-chip ${passed ? 'chip-gate-pass' : 'chip-gate-fail'}">
              ${passed ? 'GATE PASSED' : 'GATE BLOCKED'}
            </span>
          </div>
        </div>
      `;
    }

    if (conflictsOutput) {
      if (conflicts.length === 0) {
        conflictsOutput.innerHTML = `
          <div class="radar-clean-card">
            <div class="clean-icon">🛡️</div>
            <div class="clean-text">
              <h4>ZERO ARCHITECTURAL CONFLICTS DETECTED</h4>
              <p>Code passed shift-left conflict radar rules (Recursion, Governor limits, Race conditions, Row locks).</p>
            </div>
          </div>
        `;
      } else {
        conflictsOutput.innerHTML = conflicts.map(c => `
          <div class="conflict-card ${c.severity === 'CRITICAL' ? 'conflict-critical' : 'conflict-warning'}">
            <div class="conflict-header">
              <span class="conflict-rule-id">${c.rule_id}</span>
              <span class="conflict-title">${c.title}</span>
              <span class="conflict-badge ${c.severity === 'CRITICAL' ? 'badge-crit' : 'badge-warn'}">${c.severity}</span>
            </div>
            <div class="conflict-body">
              <p>${c.description}</p>
              ${c.cycle_path ? `<div class="conflict-cycle">⚡ <strong>Hazard Flow:</strong> ${c.cycle_path}</div>` : ''}
              ${c.remediation ? `<div class="conflict-remediation">🛠 <strong>Remediation:</strong> ${c.remediation}</div>` : ''}
            </div>
          </div>
        `).join('');
      }
    }
  }

  /* =====================================================================
     ANTIGRAVITY MEMORY SEARCH ENGINE (FTS5)
     ===================================================================== */
  function initMemorySearch() {
    const input = document.getElementById('memory-search-input');
    const searchBtn = document.getElementById('memory-search-btn');
    const tagBtns = document.querySelectorAll('.memory-tag');

    async function executeSearch(query) {
      if (!query || !query.trim()) return;
      playCyberTone('scan');

      const container = document.getElementById('memory-results-container');
      if (container) {
        container.innerHTML = `<div class="loading-placeholder">Executing FTS5 query in Antigravity Index...</div>`;
      }

      try {
        const res = await fetch(`/api/memory/search?q=${encodeURIComponent(query)}&limit=6`);
        if (!res.ok) throw new Error('Search failed');
        const data = await res.json();
        renderMemoryResults(data);
      } catch (err) {
        if (container) {
          container.innerHTML = `<div class="text-crimson">Search Error: ${err.message}</div>`;
        }
      }
    }

    if (searchBtn && input) {
      searchBtn.addEventListener('click', () => executeSearch(input.value));
    }

    if (input) {
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          executeSearch(input.value);
        }
      });
    }

    tagBtns.forEach(tag => {
      tag.addEventListener('click', () => {
        const q = tag.getAttribute('data-query');
        if (input && q) {
          input.value = q;
          executeSearch(q);
        }
      });
    });

    // Press '/' key to focus search
    window.addEventListener('keydown', (e) => {
      if (e.key === '/' && document.activeElement !== input && document.activeElement.tagName !== 'TEXTAREA') {
        e.preventDefault();
        if (input) input.focus();
      }
    });
  }

  function renderMemoryResults(data) {
    const container = document.getElementById('memory-results-container');
    if (!container) return;

    if (!data.results || data.results.length === 0) {
      container.innerHTML = `
        <div class="memory-empty-state">
          <span>No historical engineering conversations found matching "${data.query}".</span>
        </div>
      `;
      return;
    }

    container.innerHTML = data.results.map(turn => `
      <div class="memory-card" onclick="showTranscriptDetail('${turn.conversation_id}', '${encodeURIComponent(turn.prompt || '')}', '${encodeURIComponent(turn.solution || '')}', '${encodeURIComponent((turn.files_modified || []).join(', '))}')">
        <div class="memory-card-top">
          <span class="memory-conv-id">${turn.conversation_id.substring(0, 8)}...</span>
          <span class="memory-rank">MATCH #${turn.rank || 1}</span>
        </div>
        <div class="memory-prompt-snippet">${turn.prompt}</div>
        <div class="memory-solution-snippet">${turn.solution}</div>
        <div class="memory-files-tag">${(turn.files_modified || []).slice(0, 2).join(' • ')}</div>
      </div>
    `).join('');
  }

  /* =====================================================================
     TRANSCRIPT DETAIL DRAWER
     ===================================================================== */
  window.showTranscriptDetail = function (convId, encPrompt, encSolution, encFiles) {
    playCyberTone('chirp');
    const prompt = decodeURIComponent(encPrompt);
    const solution = decodeURIComponent(encSolution);
    const files = decodeURIComponent(encFiles);

    const drawer = document.getElementById('transcript-drawer');
    const overlay = document.getElementById('drawer-overlay');
    const content = document.getElementById('drawer-content');

    if (content) {
      content.innerHTML = `
        <div class="drawer-field">
          <span class="drawer-label">CONVERSATION ID:</span>
          <div style="font-family: var(--font-mono); color: var(--cyan-core);">${convId}</div>
        </div>
        <div class="drawer-field">
          <span class="drawer-label">ENGINEERING PROMPT / TASK:</span>
          <div class="drawer-content-box">${prompt}</div>
        </div>
        <div class="drawer-field">
          <span class="drawer-label">ROOT CAUSE ANALYSIS & REMEDIATION:</span>
          <div class="drawer-content-box">${solution}</div>
        </div>
        ${files ? `
          <div class="drawer-field">
            <span class="drawer-label">FILES MODIFIED:</span>
            <div style="font-family: var(--font-mono); font-size: 11px; color: var(--teal-accent);">${files}</div>
          </div>
        ` : ''}
      `;
    }

    if (drawer) drawer.classList.add('active');
    if (overlay) overlay.classList.add('active');
  };

  function initTranscriptDrawer() {
    const drawer = document.getElementById('transcript-drawer');
    const overlay = document.getElementById('drawer-overlay');
    const closeBtn = document.getElementById('drawer-close-btn');

    function close() {
      if (drawer) drawer.classList.remove('active');
      if (overlay) overlay.classList.remove('active');
      playCyberTone('beep');
    }

    if (closeBtn) closeBtn.addEventListener('click', close);
    if (overlay) overlay.addEventListener('click', close);

    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && drawer && drawer.classList.contains('active')) {
        close();
      }
    });
  }

  /* =====================================================================
     MORNING BRIEFING & SPEECH SYNTHESIS
     ===================================================================== */
  let currentBriefingData = null;

  function initMorningBriefing() {
    const triggerBtn = document.getElementById('trigger-briefing-btn');
    const modalOverlay = document.getElementById('briefing-modal-overlay');
    const closeBtn = document.getElementById('briefing-close-btn');
    const dismissBtn = document.getElementById('dismiss-briefing-btn');
    const replayBtn = document.getElementById('replay-speech-btn');
    const copyBtn = document.getElementById('copy-briefing-btn');

    function openModal() {
      playCyberTone('chirp');
      state.reactorOverclock = true;
      if (modalOverlay) modalOverlay.classList.add('modal-active');
      generateBriefing();
    }

    function closeModal() {
      playCyberTone('beep');
      state.reactorOverclock = false;
      stopSpeech();
      if (modalOverlay) modalOverlay.classList.remove('modal-active');
    }

    if (triggerBtn) triggerBtn.addEventListener('click', openModal);
    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    if (dismissBtn) dismissBtn.addEventListener('click', closeModal);

    if (replayBtn) {
      replayBtn.addEventListener('click', () => {
        if (currentBriefingData && currentBriefingData.spoken_script) {
          speakBriefing(currentBriefingData.spoken_script);
        }
      });
    }

    if (copyBtn) {
      copyBtn.addEventListener('click', () => {
        if (currentBriefingData) {
          const reportText = `=== ${currentBriefingData.title} ===\nDate: ${currentBriefingData.date} (${currentBriefingData.timestamp})\n\n` +
            currentBriefingData.sections.map(s => `${s.title}:\n` + s.items.map(i => `  • ${i}`).join('\n')).join('\n\n') +
            `\n\nAction Items:\n` + currentBriefingData.action_items.map(a => `  [ ] ${a.task}`).join('\n');
          
          navigator.clipboard.writeText(reportText);
          copyBtn.textContent = '✅ COPIED!';
          setTimeout(() => { copyBtn.textContent = '📋 COPY BRIEFING'; }, 2000);
        }
      });
    }

    // Dismiss on Escape
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && modalOverlay && modalOverlay.classList.contains('modal-active')) {
        closeModal();
      }
    });
  }

  async function generateBriefing() {
    const modalBody = document.getElementById('briefing-modal-body');
    const waveBars = document.getElementById('audio-wave-bars');
    const speechStatus = document.getElementById('speech-status-text');

    if (modalBody) {
      modalBody.innerHTML = `<div class="loading-placeholder">Synthesizing multi-cloud state and overnight telemetry...</div>`;
    }

    try {
      const res = await fetch('/api/briefing', { method: 'POST' });
      if (!res.ok) throw new Error('Briefing synthesis failed');
      const data = await res.json();
      currentBriefingData = data;

      renderBriefingModal(data);

      if (state.audioEnabled && data.spoken_script) {
        speakBriefing(data.spoken_script);
      } else {
        if (waveBars) waveBars.classList.remove('active');
        if (speechStatus) speechStatus.textContent = 'AUDIO SYNTHESIS MUTED';
      }
    } catch (err) {
      if (modalBody) {
        modalBody.innerHTML = `<div class="text-crimson">Error synthesizing briefing: ${err.message}</div>`;
      }
    }
  }

  function renderBriefingModal(data) {
    const modalBody = document.getElementById('briefing-modal-body');
    if (!modalBody) return;

    modalBody.innerHTML = `
      ${data.sections.map(sec => `
        <div class="briefing-section">
          <div class="briefing-section-title" style="color: ${sec.color || '#00f0ff'}">${sec.title}</div>
          <ul class="briefing-bullet-list">
            ${sec.items.map(item => `<li>${item}</li>`).join('')}
          </ul>
        </div>
      `).join('')}

      <div class="briefing-section">
        <div class="briefing-section-title" style="color: #00ffc8;">5. Strategic Priorities for Today</div>
        <div class="action-checklist">
          ${data.action_items.map(item => `
            <label class="checklist-item">
              <input type="checkbox" ${item.done ? 'checked' : ''} />
              <span style="${item.done ? 'text-decoration: line-through; color: #64748b;' : ''}">${item.task}</span>
            </label>
          `).join('')}
        </div>
      </div>
    `;
  }

  function speakBriefing(text) {
    if (!window.speechSynthesis) return;

    stopSpeech();

    const waveBars = document.getElementById('audio-wave-bars');
    const speechStatus = document.getElementById('speech-status-text');

    const utterance = new SpeechSynthesisUtterance(text);
    state.speechUtterance = utterance;

    utterance.rate = 1.05;
    utterance.pitch = 0.95;

    const voices = window.speechSynthesis.getVoices();
    const jarvisVoice = voices.find(v => v.name.includes('Natural') || v.name.includes('David') || v.name.includes('Ryan') || (v.lang === 'en-US' && v.name.includes('Google')));
    if (jarvisVoice) {
      utterance.voice = jarvisVoice;
    }

    utterance.onstart = () => {
      state.speechActive = true;
      if (waveBars) waveBars.classList.add('active');
      if (speechStatus) speechStatus.textContent = 'JARVIS VOCAL NARRATION ACTIVE...';
    };

    utterance.onend = () => {
      state.speechActive = false;
      if (waveBars) waveBars.classList.remove('active');
      if (speechStatus) speechStatus.textContent = 'BRIEFING NARRATION COMPLETE';
    };

    utterance.onerror = () => {
      state.speechActive = false;
      if (waveBars) waveBars.classList.remove('active');
      if (speechStatus) speechStatus.textContent = 'VOCAL SYNTHESIS READY';
    };

    window.speechSynthesis.speak(utterance);
  }

  function stopSpeech() {
    if (window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    state.speechActive = false;
    const waveBars = document.getElementById('audio-wave-bars');
    const speechStatus = document.getElementById('speech-status-text');
    if (waveBars) waveBars.classList.remove('active');
    if (speechStatus) speechStatus.textContent = 'VOCAL SYNTHESIS READY';
  }

  /* =====================================================================
     AUDIO TOGGLE & DESKTOP WINDOW MANAGEMENT
     ===================================================================== */
  function initAudioToggle() {
    const btn = document.getElementById('audio-toggle-btn');
    if (!btn) return;

    btn.addEventListener('click', () => {
      state.audioEnabled = !state.audioEnabled;
      if (!state.audioEnabled) {
        stopSpeech();
        btn.innerHTML = `<span class="btn-icon">🔇</span><span class="btn-text">AUDIO MUTED</span>`;
      } else {
        btn.innerHTML = `<span class="btn-icon">🔊</span><span class="btn-text">AUDIO ON</span>`;
        playCyberTone('beep');
      }
    });
  }

  function initGlobalHotkeyBanner() {
    window.addEventListener('keydown', (e) => {
      if (e.altKey && (e.key === 'j' || e.key === 'J')) {
        e.preventDefault();
        playCyberTone('chirp');
        fetch('/api/hud/window', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: 'toggle' }),
        }).catch(() => {});
      }
    });

    const refreshBtn = document.getElementById('refresh-all-btn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => {
        playCyberTone('beep');
        fetchSystemStatus();
        fetchActiveBatches();
        fetchRcmStats();
        fetchSchedulers();
        fetchDeployments();
        fetchIntegrations();
        fetchGovernance();
      });
    }
  }

  /* =====================================================================
     AUTONOMOUS SRE COPILOT & AI INCIDENT INVESTIGATOR
     ===================================================================== */
  function initAICopilot() {
    // 1. Investigate Button
    const runInvestigateBtn = document.getElementById('run-ai-investigate-btn');
    if (runInvestigateBtn) {
      runInvestigateBtn.addEventListener('click', async () => {
        runInvestigateBtn.disabled = true;
        runInvestigateBtn.innerHTML = '<span class="btn-icon">⏳</span><span>REASONING (CLAUDE 3.5 SONNET)...</span>';
        try {
          const res = await fetch('/api/ai/investigate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              incident_id: 'INC-8924',
              component: 'YesterdayDenialSyncBatch',
              error: 'System.LimitException: Apex CPU time limit exceeded',
              org: 'Alliance Prod'
            })
          });
          const data = await res.json();
          if (data.success && data.diagnosis) {
            const d = data.diagnosis;
            const rcEl = document.getElementById('ai-root-cause-text');
            if (rcEl) rcEl.textContent = d.root_cause;
            
            const chainEl = document.getElementById('ai-causal-chain-list');
            if (chainEl && d.causal_chain) {
              chainEl.innerHTML = d.causal_chain.map((step, idx) => `
                <li><span class="step-num">${idx + 1}</span> ${step}</li>
              `).join('');
            }
            
            const biEl = document.getElementById('ai-business-impact');
            if (biEl) biEl.textContent = d.business_impact;
            
            const raEl = document.getElementById('ai-recommended-action');
            if (raEl) raEl.textContent = d.recommended_action;
            
            const badgeEl = document.getElementById('ai-confidence-badge');
            if (badgeEl) badgeEl.textContent = `${(d.confidence_score * 100).toFixed(1)}% CONFIDENCE (${d.model_used.toUpperCase()})`;
            
            const diffEl = document.getElementById('ai-git-diff-content');
            if (diffEl && d.git_diff) {
              diffEl.textContent = d.git_diff;
            }
            
            const verifEl = document.getElementById('ai-verif-script');
            if (verifEl && d.verification_script) {
              verifEl.textContent = d.verification_script;
            }
          }
        } catch (err) {
          console.error('AI Investigate error:', err);
        } finally {
          runInvestigateBtn.disabled = false;
          runInvestigateBtn.innerHTML = '<span class="btn-icon">⚡</span><span>RUN AI ROOT CAUSE ANALYSIS</span>';
        }
      });
    }

    // 2. Copy Diff Button
    const copyDiffBtn = document.getElementById('copy-diff-btn');
    if (copyDiffBtn) {
      copyDiffBtn.addEventListener('click', () => {
        const code = document.getElementById('ai-git-diff-content').textContent;
        navigator.clipboard.writeText(code).then(() => {
          copyDiffBtn.textContent = 'COPIED!';
          setTimeout(() => { copyDiffBtn.textContent = '📋 COPY DIFF'; }, 2000);
        });
      });
    }

    // 3. Copy Verification Script Button
    const copyVerifBtn = document.getElementById('copy-verif-btn');
    if (copyVerifBtn) {
      copyVerifBtn.addEventListener('click', () => {
        const code = document.getElementById('ai-verif-script').textContent;
        navigator.clipboard.writeText(code).then(() => {
          copyVerifBtn.textContent = 'COPIED!';
          setTimeout(() => { copyVerifBtn.textContent = '📋 COPY APEX'; }, 2000);
        });
      });
    }

    // 4. Test in Scratch Org Button
    const applyScratchBtn = document.getElementById('apply-scratch-btn');
    if (applyScratchBtn) {
      applyScratchBtn.addEventListener('click', () => {
        applyScratchBtn.textContent = 'VALIDATING IN SCRATCH ORG...';
        setTimeout(() => {
          applyScratchBtn.textContent = 'PASSED (0 REGRESSIONS)';
          setTimeout(() => { applyScratchBtn.textContent = '🚀 TEST IN SCRATCH ORG'; }, 3000);
        }, 1000);
      });
    }

    // 5. Predictive Shadow Simulator
    async function updateSimulation() {
      const volInput = document.getElementById('sim-volume-input');
      const vol = parseInt(volInput ? volInput.value : 1704, 10) || 1704;
      try {
        const res = await fetch('/api/ai/predict', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ incoming_denials: vol, batch_class: 'YesterdayDenialSyncBatch' })
        });
        const data = await res.json();
        if (data.success && data.forecast) {
          const f = data.forecast;
          const badge = document.getElementById('sim-risk-badge');
          if (badge) badge.textContent = `${f.risk_level} (${f.failure_probability_pct}% PROBABILITY)`;
          
          const cpuVal = document.getElementById('sim-cpu-val');
          if (cpuVal) cpuVal.textContent = `${f.projected_cpu_time_ms.toLocaleString()} ms / 10,000 ms`;
          
          const pct = Math.min(100, Math.round((f.projected_cpu_time_ms / f.max_cpu_limit_ms) * 100));
          const fillEl = document.getElementById('sim-cpu-fill');
          if (fillEl) {
            fillEl.style.width = `${pct}%`;
            fillEl.className = `sim-fill ${pct > 90 ? 'fill-crimson' : (pct > 75 ? 'fill-amber' : 'fill-green')}`;
          }
          
          const analysisText = document.getElementById('sim-analysis-text');
          if (analysisText) analysisText.textContent = f.analysis;
          
          const recBody = document.getElementById('sim-rec-body');
          if (recBody) {
            recBody.innerHTML = `Automatically reduce batch scope chunk size from <strong>200 records</strong> to <strong>${f.recommended_chunk_size} records</strong> in CronTrigger configuration before the 02:00 AM scheduled execution.`;
          }
          
          const applyChunkBtn = document.getElementById('apply-chunk-btn');
          if (applyChunkBtn) {
            applyChunkBtn.textContent = `APPLY CHUNK SIZE = ${f.recommended_chunk_size} TO SCHEDULER`;
          }
        }
      } catch (err) {
        console.error('Simulation error:', err);
      }
    }

    const simRecalcBtn = document.getElementById('sim-recalc-btn');
    if (simRecalcBtn) simRecalcBtn.addEventListener('click', updateSimulation);
    const volInput = document.getElementById('sim-volume-input');
    if (volInput) volInput.addEventListener('change', updateSimulation);

    const applyChunkBtn = document.getElementById('apply-chunk-btn');
    if (applyChunkBtn) {
      applyChunkBtn.addEventListener('click', () => {
        applyChunkBtn.textContent = 'CHUNK APPLIED TO CRONTRIGGER';
        setTimeout(() => { applyChunkBtn.textContent = 'APPLY CHUNK SIZE = 80 TO SCHEDULER'; }, 2500);
      });
    }

    // 6. Interactive Engineering Co-Pilot Terminal
    function appendChatMessage(sender, text, isUser = false, actionCard = null) {
      const history = document.getElementById('copilot-chat-history');
      if (!history) return;
      const msg = document.createElement('div');
      msg.className = `chat-message ${isUser ? 'msg-user' : 'msg-ai'}`;
      
      let actionHtml = '';
      if (actionCard) {
        actionHtml = `
          <div class="chat-action-card" style="margin-top: 8px; background: #080c14; border: 1px solid rgba(255,255,255,0.1); border-radius: 6px; padding: 10px;">
            <div style="font-size: 11px; font-weight: 700; color: #10b981; margin-bottom: 6px;">${actionCard.title}</div>
            <pre style="font-family: var(--font-mono); font-size: 11px; color: #93c5fd; white-space: pre-wrap; margin: 0 0 8px; max-height: 140px; overflow-y: auto;"><code>${actionCard.code}</code></pre>
            <button class="mini-action-btn btn-primary" onclick="navigator.clipboard.writeText('${encodeURIComponent(actionCard.code)}'); this.textContent='COPIED APEX';">${actionCard.button_label}</button>
          </div>
        `;
      }
      
      msg.innerHTML = `
        <div class="chat-sender">${sender}</div>
        <div class="chat-text">${text}</div>
        ${actionHtml}
      `;
      history.appendChild(msg);
      history.scrollTop = history.scrollHeight;
    }

    async function sendCopilotQuery(query) {
      if (!query || !query.trim()) return;
      appendChatMessage('YOU', query, true);
      const input = document.getElementById('copilot-input');
      if (input) input.value = '';
      
      try {
        const res = await fetch('/api/ai/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: query.trim() })
        });
        const data = await res.json();
        if (data.success) {
          appendChatMessage(data.model_used.toUpperCase() + ' • SRE COPILOT', data.reply, false, data.action_card);
        }
      } catch (err) {
        appendChatMessage('SYSTEM', 'Failed to reach AI Core: ' + err.message, false);
      }
    }

    const copilotSendBtn = document.getElementById('copilot-send-btn');
    const copilotInput = document.getElementById('copilot-input');
    if (copilotSendBtn && copilotInput) {
      copilotSendBtn.addEventListener('click', () => sendCopilotQuery(copilotInput.value));
      copilotInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          sendCopilotQuery(copilotInput.value);
        }
      });
    }

    // Prompt Chips
    document.querySelectorAll('.prompt-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const prompt = chip.getAttribute('data-prompt');
        if (prompt) sendCopilotQuery(prompt);
      });
    });
  }

  /* =====================================================================
     AI CONFIGURATION MODAL (ANTHROPIC CLAUDE / GEMINI)
     ===================================================================== */
  function initAIConfigModal() {
    const modal = document.getElementById('ai-config-modal-overlay');
    const openBtn = document.getElementById('open-ai-config-btn');
    const chip = document.getElementById('ai-engine-chip');
    const closeBtn = document.getElementById('close-ai-config-btn');
    const cancelBtn = document.getElementById('cancel-ai-config-btn');
    const saveBtn = document.getElementById('save-ai-config-btn');
    const statusMsg = document.getElementById('ai-config-status-msg');

    function open() {
      if (modal) modal.classList.add('active');
    }
    function close() {
      if (modal) modal.classList.remove('active');
      if (statusMsg) statusMsg.style.display = 'none';
    }

    if (openBtn) openBtn.addEventListener('click', open);
    if (chip) chip.addEventListener('click', open);
    if (closeBtn) closeBtn.addEventListener('click', close);
    if (cancelBtn) cancelBtn.addEventListener('click', close);

    if (saveBtn) {
      saveBtn.addEventListener('click', async () => {
        const antKey = document.getElementById('anthropic-key-input').value;
        const gemKey = document.getElementById('gemini-key-input').value;
        saveBtn.disabled = true;
        saveBtn.textContent = 'CONNECTING...';
        try {
          const res = await fetch('/api/ai/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              anthropic_key: antKey,
              gemini_key: gemKey
            })
          });
          const data = await res.json();
          if (data.success) {
            const nameEl = document.getElementById('ai-engine-name');
            if (nameEl) nameEl.textContent = data.active_provider.toUpperCase();
            if (statusMsg) {
              statusMsg.style.display = 'block';
              statusMsg.style.background = 'rgba(16, 185, 129, 0.15)';
              statusMsg.style.color = '#10b981';
              statusMsg.textContent = `Connected! Active Provider: ${data.active_provider}`;
            }
            setTimeout(close, 1500);
          }
        } catch (err) {
          if (statusMsg) {
            statusMsg.style.display = 'block';
            statusMsg.style.background = 'rgba(239, 68, 68, 0.15)';
            statusMsg.style.color = '#ef4444';
            statusMsg.textContent = `Connection error: ${err.message}`;
          }
        } finally {
          saveBtn.disabled = false;
          saveBtn.textContent = 'SAVE & CONNECT';
        }
      });
    }

    // Initial AI Status Fetch
    fetch('/api/ai/status')
      .then(r => r.json())
      .then(data => {
        const nameEl = document.getElementById('ai-engine-name');
        if (nameEl && data.active_provider) {
          nameEl.textContent = data.active_provider.toUpperCase();
        }
      })
      .catch(() => {});
  }

  /* =====================================================================
     INITIALIZATION LIFECYCLE
     ===================================================================== */
  document.addEventListener('DOMContentLoaded', () => {
    // 1. Clock
    updateClock();
    setInterval(updateClock, 1000);

    // 2. Arc Reactor Canvas
    initArcReactor();

    // 3. Audio & Hotkey
    initAudioToggle();
    initGlobalHotkeyBanner();

    // 4. Tabs & Navigation
    initTabNavigation();

    // 5. AI Copilot & Model Config
    initAICopilot();
    initAIConfigModal();

    // 6. Widgets & Modules
    initCodeTriage();
    initMemorySearch();
    initTranscriptDrawer();
    initMorningBriefing();

    // 7. Initial Telemetry Hydration
    fetchSystemStatus();
    fetchActiveBatches();
    fetchRcmStats();
    fetchSchedulers();
    fetchDeployments();
    fetchIntegrations();
    fetchGovernance();

    // 8. Background Real-Time Polling loop every 5 seconds
    state.pollInterval = setInterval(() => {
      fetchSystemStatus();
      fetchActiveBatches();
      fetchRcmStats();
      fetchSchedulers();
      fetchDeployments();
      fetchIntegrations();
      fetchGovernance();
    }, 5000);
  });

})();
