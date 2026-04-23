using UnityEngine;
using System.Net.Sockets;
using System.IO;
using System.Threading;
using System.Collections.Generic;
using TMPro;

public class DGMonitor : MonoBehaviour
{
    [Header("DG Settings")]
    public string dgID = "DG1";
    public string ipAddress = "127.0.0.1";
    public int port = 5006;    // ← different port from transformer!

    [Header("Thresholds")]
    public float fuelWarning = 30f;     // orange below this
    public float coolantMax = 95f;     // red above this

    [Header("Visuals")]
    public Renderer dgRenderer;
    public GameObject alertLight;

    [Header("UI Display")]
    public GameObject dataPanel;
    public TextMeshProUGUI voltageText;
    public TextMeshProUGUI currentText;
    public TextMeshProUGUI rpmText;
    public TextMeshProUGUI fuelText;
    public TextMeshProUGUI coolantText;
    public TextMeshProUGUI statusText;

    // Thread safe queue
    private Queue<string> dataQueue = new Queue<string>();
    private object queueLock = new object();
    private TcpClient client;
    private StreamReader reader;
    private Thread dataThread;
    private bool isRunning = false;

    // Current values
    private float voltage, current, rpm, fuel, coolant;
    private string status = "CONNECTING...";

    // DG States
    private bool isRunningDG = false;
    private bool isFuelLow = false;
    private bool isOverheat = false;

    // Colors
    private Color greyColor = new Color(0.5f, 0.5f, 0.5f);  // standby
    private Color greenColor = new Color(0f, 1f, 0f);     // running
    private Color orangeColor = new Color(1f, 0.65f, 0f);    // warning
    private Color redColor = new Color(1f, 0f, 0f);     // fault

    void Start()
    {
        Debug.Log($"[{dgID}] DGMonitor Starting on port {port}...");

        // Start grey (standby)
        ApplyColor(greyColor);

        // Hide panel
        if (dataPanel != null)
            dataPanel.SetActive(true);
        else
            Debug.LogWarning($"[{dgID}] Data Panel is NULL!");

        if (dgRenderer == null)
            Debug.LogWarning($"[{dgID}] Renderer is NULL!");

        // Start connection thread
        isRunning = true;
        dataThread = new Thread(ConnectAndReceive);
        dataThread.IsBackground = true;
        dataThread.Start();
    }

    // ── Background Thread ──────────────────────────────────────────
    void ConnectAndReceive()
    {
        while (isRunning)
        {
            try
            {
                Debug.Log($"[{dgID}] Connecting to Python on port {port}...");
                client = new TcpClient();
                client.Connect(ipAddress, port);
                Debug.Log($"[{dgID}] Connected!");

                reader = new StreamReader(client.GetStream());

                while (isRunning)
                {
                    string line = reader.ReadLine();
                    if (line == null) break;
                    if (string.IsNullOrEmpty(line)) continue;

                    lock (queueLock)
                    {
                        dataQueue.Enqueue(line);
                    }
                }
            }
            catch (System.Exception e)
            {
                Debug.LogWarning($"[{dgID}] Error: {e.Message}");
            }
            finally
            {
                client?.Close();
            }

            if (isRunning)
            {
                Debug.Log($"[{dgID}] Retrying in 2 seconds...");
                Thread.Sleep(2000);
            }
        }
    }

    // ── Main Thread: Process Data ──────────────────────────────────
    void Update()
    {
        string latestLine = null;

        lock (queueLock)
        {
            while (dataQueue.Count > 0)
                latestLine = dataQueue.Dequeue();
        }

        if (latestLine == null) return;
        ParseAndApply(latestLine);
    }

    void ParseAndApply(string line)
    {
        // Format: DG1,voltage,current,rpm,fuel,coolant,status
        string[] parts = line.Split(',');

        if (parts.Length < 7)
        {
            Debug.LogWarning($"[{dgID}] Bad data: {line}");
            return;
        }

        if (parts[0].Trim() != dgID) return;

        Debug.Log($"[{dgID}] Received: {line}");

        float.TryParse(parts[1], out voltage);
        float.TryParse(parts[2], out current);
        float.TryParse(parts[3], out rpm);
        float.TryParse(parts[4], out fuel);
        float.TryParse(parts[5], out coolant);
        status = parts[6].Trim();

        // Determine DG state
        isRunningDG = (status == "RUNNING");
        isFuelLow = (fuel <= fuelWarning);
        isOverheat = (coolant >= coolantMax);

        // Apply correct color
        if (!isRunningDG)
            ApplyColor(greyColor);       // STANDBY = grey
        else if (isOverheat || isFuelLow)
            ApplyColor(orangeColor);     // WARNING = orange
        else
            ApplyColor(greenColor);      // RUNNING = green

        // Alert light
        if (alertLight != null)
            alertLight.SetActive(isOverheat || isFuelLow);

        UpdateUI();
    }

    // ── Apply Color (URP + Standard) ──────────────────────────────
    void ApplyColor(Color color)
    {
        if (dgRenderer == null) return;

        foreach (Material mat in dgRenderer.materials)
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
    }

    // ── Update UI Panel ───────────────────────────────────────────
    void UpdateUI()
    {
        if (voltageText != null)
            voltageText.text = $"Voltage  : {voltage:F0} V";

        if (currentText != null)
            currentText.text = $"Current  : {current:F1} A";

        if (rpmText != null)
            rpmText.text = $"RPM      : {rpm:F0}";

        if (fuelText != null)
        {
            fuelText.text = $"Fuel     : {fuel:F1} %";
            fuelText.color = isFuelLow ? orangeColor : greenColor;
        }

        if (coolantText != null)
        {
            coolantText.text = $"Coolant  : {coolant:F1} °C";
            coolantText.color = isOverheat ? redColor : greenColor;
        }

        if (statusText != null)
        {
            statusText.text = $"Status   : {status}";
            statusText.color = isRunningDG ? greenColor : greyColor;
        }
    }

    // ── Called by Robot ───────────────────────────────────────────
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

    // For robot patrol
    public bool IsCritical() => isOverheat || isFuelLow;
    public float GetFuel() => fuel;
    public float GetCoolant() => coolant;
    public string GetStatus() => status;

    void OnDestroy()
    {
        isRunning = false;
        dataThread?.Abort();
        client?.Close();
    }
}