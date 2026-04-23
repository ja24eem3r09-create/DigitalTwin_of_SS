using UnityEngine;
using System.Net.Sockets;
using System.IO;
using System.Threading;
using System.Collections;
using System.Collections.Generic;

public class CommandReceiver : MonoBehaviour
{
    [Header("References")]
    public Camera mainCamera;
    public RobotPatrol robot;

    [Header("Equipment Transforms")]
    public Transform transformerT2;
    public Transform dgTransform;

    private Queue<string> commandQueue = new Queue<string>();
    private object queueLock = new object();
    private bool isRunning = false;

    void Start()
    {
        isRunning = true;
        Debug.Log("[CommandReceiver] Started! Waiting for dashboard commands...");
    }

    // ── Called by TransformerMonitor after connecting ──────────
    // We reuse the SAME connection (port 5005)
    // Commands come mixed with data!
    public void ProcessLine(string line)
    {
        if (line.StartsWith("FOCUS:"))
        {
            lock (queueLock)
            {
                commandQueue.Enqueue(line);
            }
        }
    }

    void Update()
    {
        string command = null;
        lock (queueLock)
        {
            if (commandQueue.Count > 0)
                command = commandQueue.Dequeue();
        }

        if (command == null) return;
        HandleCommand(command);
    }

    void HandleCommand(string command)
    {
        Debug.Log("[CommandReceiver] Command: " + command);

        if (!command.StartsWith("FOCUS:")) return;

        string id = command.Replace("FOCUS:", "").Trim();

        Transform target = null;
        switch (id)
        {
            case "T2": target = transformerT2; break;
            case "DG1": target = dgTransform; break;
        }

        if (target == null)
        {
            Debug.LogWarning($"[CommandReceiver] Unknown equipment: {id}");
            return;
        }

        // Move camera to equipment
        StartCoroutine(FlyCamera(target));

        // Send robot to equipment
        if (robot != null)
            robot.GoToEquipment(target.position);

        Debug.Log($"[CommandReceiver] Focusing on: {id}");
    }

    IEnumerator FlyCamera(Transform target)
    {
        if (mainCamera == null) yield break;

        Vector3 targetPos = target.position +
                           new Vector3(0, 4, -6);
        Quaternion targetRot = Quaternion.LookRotation(
            target.position - targetPos);

        Vector3 startPos = mainCamera.transform.position;
        Quaternion startRot = mainCamera.transform.rotation;

        float elapsed = 0f;
        float duration = 2f;

        while (elapsed < duration)
        {
            elapsed += Time.deltaTime;
            float t = Mathf.SmoothStep(0, 1, elapsed / duration);

            mainCamera.transform.position = Vector3.Lerp(
                startPos, targetPos, t);
            mainCamera.transform.rotation = Quaternion.Slerp(
                startRot, targetRot, t);

            yield return null;
        }
    }
}