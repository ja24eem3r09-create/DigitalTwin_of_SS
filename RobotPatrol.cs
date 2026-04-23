using UnityEngine;
using UnityEngine.AI;
using TMPro;
using System.Collections;

public class RobotPatrol : MonoBehaviour
{
    [Header("Waypoints")]
    public Transform[] waypoints;
    public float inspectionTime = 5f;
    public float arrivalDistance = 1.5f;

    [Header("GTA Style Movement")]
    public float rotationSpeed = 8f;        // Smooth turning speed
    public float walkAnimSpeed = 1f;        // Animation speed

    [Header("Robot Animator")]
    public Animator robotAnimator;

    [Header("AI Status UI")]
    public TextMeshProUGUI robotStatusText;

    // Internals
    private NavMeshAgent agent;
    private int currentWaypoint = 0;
    private bool isInspecting = false;
    private Vector3 lastPosition;

    void Start()
    {
        agent = GetComponent<NavMeshAgent>();

        // KEY FIX: These settings make GTA style movement
        agent.updateRotation = true;
        agent.updateUpAxis = true;
        agent.angularSpeed = 360f;   // ← MAX turning
        agent.acceleration = 999f;   // ← instant start
        agent.speed = 3.5f;
        agent.stoppingDistance = 1.5f;
        agent.autoBraking = true;

        // MOST IMPORTANT: Turn OFF root motion
        if (robotAnimator != null)
            robotAnimator.applyRootMotion = false;

        // Also find animator on child
        Animator childAnim = GetComponentInChildren<Animator>();
        if (childAnim != null)
            childAnim.applyRootMotion = false;

        lastPosition = transform.position;

        if (waypoints.Length > 0)
            MoveToNext();

        Debug.Log("[Robot] Started! Waypoints: " + waypoints.Length);
    }

    void Update()
    {
        if (isInspecting) return;

        Vector3 velocity = agent.velocity;
        velocity.y = 0f;
        float speed = velocity.magnitude;

        // Normalized speed 0 to 1
        float normalizedSpeed = Mathf.Clamp01(
            speed / agent.speed);

        // Calculate turn direction -1 to 1
        float direction = 0f;
        if (speed > 0.1f)
        {
            float angle = Vector3.SignedAngle(
                transform.forward,
                velocity.normalized,
                Vector3.up);
            direction = Mathf.Clamp(angle / 90f, -1f, 1f);
        }

        // Set both parameters
        if (robotAnimator != null)
        {
            robotAnimator.SetFloat("Speed",
                normalizedSpeed, 0.1f, Time.deltaTime);
            robotAnimator.SetFloat("Direction",
                direction, 0.1f, Time.deltaTime);
        }

        // Debug to verify values
        Debug.Log($"Speed:{normalizedSpeed:F2} Dir:{direction:F2}");

        // Check arrival
        if (!agent.pathPending &&
            agent.remainingDistance <= agent.stoppingDistance &&
            agent.velocity.magnitude < 0.2f &&
            !isInspecting)
        {
            StartCoroutine(InspectWaypoint());
        }
    }

    void MoveToNext()
    {
        if (waypoints.Length == 0) return;

        Transform target = waypoints[currentWaypoint];
        agent.isStopped = false;
        agent.SetDestination(target.position);

        UpdateStatus($"🚶 Walking to → {target.name}");
        Debug.Log($"[Robot] Moving to {target.name}");
    }

    IEnumerator InspectWaypoint()
    {
        if (isInspecting) yield break;
        isInspecting = true;
        agent.isStopped = true;

        if (robotAnimator != null)
            robotAnimator.SetFloat("Speed", 0f);

        Transform wp = waypoints[currentWaypoint];
        string wpName = wp.name;

        // Face the equipment
        yield return StartCoroutine(FaceTarget(wp.position));

        // ── Check for TransformerMonitor ──────────────────────────
        TransformerMonitor trMonitor =
            wp.GetComponentInParent<TransformerMonitor>();
        if (trMonitor == null)
            trMonitor = wp.GetComponentInChildren<TransformerMonitor>();

        // ── Check for DGMonitor ───────────────────────────────────
        DGMonitor dgMonitor =
            wp.GetComponentInParent<DGMonitor>();
        if (dgMonitor == null)
            dgMonitor = wp.GetComponentInChildren<DGMonitor>();

        // ── Show correct panel ────────────────────────────────────
        if (trMonitor != null)
        {
            trMonitor.ShowDataPanel();
            UpdateStatus(trMonitor.IsCritical()
                ? $"⚠️ ALERT! {wpName} Temp: {trMonitor.GetTemperature():F1}°C CRITICAL!"
                : $"✅ {wpName} Temp: {trMonitor.GetTemperature():F1}°C SAFE");
        }
        else if (dgMonitor != null)
        {
            dgMonitor.ShowDataPanel();
            UpdateStatus(dgMonitor.IsCritical()
                ? $"⚠️ DG WARNING! Fuel:{dgMonitor.GetFuel():F1}% Coolant:{dgMonitor.GetCoolant():F1}°C"
                : $"✅ DG {dgMonitor.GetStatus()} — Fuel:{dgMonitor.GetFuel():F1}%");
        }
        else
        {
            UpdateStatus($"🔍 Inspecting {wpName}...");
        }

        yield return new WaitForSeconds(inspectionTime);

        // Hide panels
        if (trMonitor != null) trMonitor.HideDataPanel();
        if (dgMonitor != null) dgMonitor.HideDataPanel();

        // Next waypoint
        currentWaypoint = (currentWaypoint + 1) % waypoints.Length;
        isInspecting = false;
        MoveToNext();



    }

    // ── Smooth Turn to Face Target (GTA Style) ─────────────────────────────
    IEnumerator FaceTarget(Vector3 targetPos)
    {
        Vector3 direction = (targetPos - transform.position).normalized;
        direction.y = 0f;

        if (direction == Vector3.zero) yield break;

        Quaternion targetRot = Quaternion.LookRotation(direction);

        // Smoothly rotate until facing target
        while (Quaternion.Angle(transform.rotation, targetRot) > 3f)
        {
            transform.rotation = Quaternion.RotateTowards(
                transform.rotation,
                targetRot,
                240f * Time.deltaTime    // 240 degrees per second
            );
            yield return null;
        }

        transform.rotation = targetRot;
    }
    void UpdateStatus(string msg)
    {
        if (robotStatusText != null)
            robotStatusText.text = msg;
        Debug.Log("[Robot] " + msg);
    }
    // ── Called from Dashboard "View in 3D" button ──────────────────
    public void GoToEquipment(Vector3 position)
    {
        // Stop current patrol
        isInspecting = false;
        agent.isStopped = false;

        // Go directly to clicked equipment
        agent.SetDestination(position);

        UpdateStatus("📡 Dashboard Command Received! Going to equipment...");
        Debug.Log("[Robot] Dashboard triggered! Moving to: " + position);
    }

}