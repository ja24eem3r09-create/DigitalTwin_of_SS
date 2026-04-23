using UnityEngine;
using System.Net.Sockets;
using System.IO;
using System.Threading;
using System.Collections.Generic;
using TMPro;

public class TransformerMonitor : MonoBehaviour
{
    [Header("Transformer Settings")]
    public string transformerID = "T2";
    public string ipAddress = "127.0.0.1";
    public int port = 5005;
    public float temperatureThreshold = 85f;

    [Header("Visuals")]
    public Renderer transformerRenderer;
    public GameObject alertLight;

    [Header("UI Display")]
    public GameObject dataPanel;
    public TextMeshProUGUI voltageText;
    public TextMeshProUGUI currentText;
    public TextMeshProUGUI powerText;
    public TextMeshProUGUI tempText;
    public TextMeshProUGUI statusText;

    // Thread safe queue
    private Queue<string> dataQueue = new Queue<string>();
    private object queueLock = new object();

    private TcpClient client;
    private StreamReader reader;
    private Thread dataThread;
    private bool isRunning = false;
    private bool isConnected = false;

    // Current values
    private float voltage, current, power, temperature;
    private string status = "CONNECTING...";
    private bool isCritical = false;

    // Colors for URP
    private Color safeColor = new Color(0f, 1f, 0f);
    private Color criticalColor = new Color(1f, 0f, 0f);

    void Start()
    {
        Debug.Log($"[{transformerID}] TransformerMonitor Starting...");

        // Set green color at start
        ApplyColor(safeColor);

        // Show panel at start
        if (dataPanel != null)
            dataPanel.SetActive(true);
        else
            Debug.LogWarning($"[{transformerID}] Data Panel is NULL!");

        // Check renderer
        if (transformerRenderer == null)
            Debug.LogWarning($"[{transformerID}] Renderer is NULL!");

        // Start connection thread
        isRunning = true;
        dataThread = new Thread(ConnectAndReceive);
        dataThread.IsBackground = true;
        dataThread.Start();
    }

    // ── Background Thread ──────────────────────────────────────
    void ConnectAndReceive()
    {
        while (isRunning)
        {
            try
            {
                Debug.Log($"[{transformerID}] Connecting to Python {ipAddress}:{port}...");
                client = new TcpClient();
                client.Connect(ipAddress, port);
                isConnected = true;
                Debug.Log($"[{transformerID}] Connected to Python!");

                reader = new StreamReader(client.GetStream());

                while (isRunning)
                {
                    string line = reader.ReadLine();
                    if (line == null) break;
                    if (string.IsNullOrEmpty(line)) continue;

                    // ── NEW: Check if dashboard sent FOCUS command ──
                    if (line.StartsWith("FOCUS:"))
                    {
                        // Forward to CommandReceiver
                        lock (queueLock)
                        {
                            dataQueue.Enqueue(line);
                        }
                        continue;
                    }

                    // Normal sensor data
                    lock (queueLock)
                    {
                        dataQueue.Enqueue(line);
                    }
                }
            }
            catch (System.Exception e)
            {
                Debug.LogWarning($"[{transformerID}] Connection error: {e.Message}");
                isConnected = false;
            }
            finally
            {
                client?.Close();
            }

            if (isRunning)
            {
                Debug.Log($"[{transformerID}] Retrying in 2 seconds...");
                Thread.Sleep(2000);
            }
        }
    }

    // ── Main Thread: Process queue every frame ─────────────────
    void Update()
    {
        string latestLine = null;

        lock (queueLock)
        {
            while (dataQueue.Count > 0)
                latestLine = dataQueue.Dequeue();
        }

        if (latestLine == null) return;

        // ── NEW: Handle FOCUS command from dashboard ────────────
        if (latestLine.StartsWith("FOCUS:"))
        {
            CommandReceiver cr = FindObjectOfType<CommandReceiver>();
            if (cr != null)
                cr.ProcessLine(latestLine);
            else
                Debug.LogWarning("[TransformerMonitor] CommandReceiver not found!");
            return;
        }

        // Normal data processing
        ParseAndApply(latestLine);
    }

    void ParseAndApply(string line)
    {
        // Format: T2,F2,11.5,1.2,13.8,45.0,SAFE
        string[] parts = line.Split(',');

        if (parts.Length < 7)
        {
            Debug.LogWarning($"[{transformerID}] Bad data: {line}");
            return;
        }

        // Only process data for THIS transformer
        if (parts[0].Trim() != transformerID)
            return;

        Debug.Log($"[{transformerID}] Received: {line}");

        float.TryParse(parts[2], out voltage);
        float.TryParse(parts[3], out current);
        float.TryParse(parts[4], out power);
        float.TryParse(parts[5], out temperature);
        status = parts[6].Trim();

        isCritical = (temperature >= temperatureThreshold);

        // Apply color
        ApplyColor(isCritical ? criticalColor : safeColor);

        // Update UI
        UpdateUI();

        // Alert light
        if (alertLight != null)
            alertLight.SetActive(isCritical);
    }

    // ── Apply Color (URP + Standard) ───────────────────────────
    void ApplyColor(Color color)
    {
        if (transformerRenderer == null)
        {
            Debug.LogError("RENDERER IS NULL!");
            return;
        }

        Material[] mats = transformerRenderer.materials;

        foreach (Material mat in mats)
        {
            if (mat.HasProperty("_BaseColor"))
                mat.SetColor("_BaseColor", color);

            if (mat.HasProperty("_Color"))
                mat.SetColor("_Color", color);

            if (mat.HasProperty("_EmissionColor"))
            {
                mat.EnableKeyword("_EMISSION");
                mat.SetColor("_EmissionColor", color * 0.4f);
            }
        }

        transformerRenderer.enabled = false;
        transformerRenderer.enabled = true;
    }

    // ── Update UI Texts ────────────────────────────────────────
    void UpdateUI()
    {
        if (voltageText != null)
            voltageText.text = $"Voltage     : {voltage:F1} kV";

        if (currentText != null)
            currentText.text = $"Current     : {current:F2} kA";

        if (powerText != null)
            powerText.text = $"Power       : {power:F1} MW";

        if (tempText != null)
            tempText.text = $"Temperature : {temperature:F1} °C";

        if (statusText != null)
        {
            statusText.text = $"Status      : {status}";
            statusText.color = isCritical ? criticalColor : safeColor;
        }
    }

    // ── Called by Robot ────────────────────────────────────────
    public void ShowDataPanel()
    {
        if (dataPanel != null)
            dataPanel.SetActive(true);
        else
            Debug.LogWarning("ShowDataPanel: dataPanel is NULL!");
    }

    public void HideDataPanel()
    {
        if (dataPanel != null)
            dataPanel.SetActive(false);
    }

    public bool IsCritical() => isCritical;
    public float GetTemperature() => temperature;
    public string GetStatus() => status;

    void OnDestroy()
    {
        isRunning = false;
        dataThread?.Abort();
        client?.Close();
    }
}