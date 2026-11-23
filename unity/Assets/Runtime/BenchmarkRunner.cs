using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using Unity.Profiling;
using UnityEngine;
using Stopwatch = System.Diagnostics.Stopwatch;

namespace SpecTuner.UnityDemo
{
    public sealed class BenchmarkRunner : MonoBehaviour
    {
        private static readonly int[] Populations = { 64, 256, 1024 };
        private static readonly CultureInfo Invariant = CultureInfo.InvariantCulture;
        private static readonly ProfilerMarker WorkloadMarker = new ProfilerMarker("SpecTuner.NpcWorkload");
        private const double WarmupSeconds = 3;
        private const double SampleSeconds = 10;
        private const int WaypointCount = 128;

        private readonly List<Sample> samples = new List<Sample>(16384);
        private readonly Vector3[] waypoints = new Vector3[WaypointCount];
        private Transform[] agents = Array.Empty<Transform>();
        private int populationIndex;
        private int frameIndex;
        private int previousVsync;
        private int previousTargetFps;
        private bool settingsApplied;
        private bool pendingSample;
        private double startedAt;
        private double previousWorkloadMs;

        private struct Sample
        {
            public int NpcCount;
            public int FrameIndex;
            public double FrameMs;
            public double WorkloadMs;
        }

        private void Start()
        {
            previousVsync = QualitySettings.vSyncCount;
            previousTargetFps = Application.targetFrameRate;
            settingsApplied = true;
            QualitySettings.vSyncCount = 0;
            Application.targetFrameRate = -1;

            var random = new System.Random(3817);
            for (int index = 0; index < waypoints.Length; index++)
                waypoints[index] = new Vector3(random.Next(-180, 181) / 10f, 0f, random.Next(-180, 181) / 10f);
            BeginScenario();
        }

        private void BeginScenario()
        {
            foreach (Transform agent in agents)
            {
                agent.gameObject.SetActive(false);
                Destroy(agent.gameObject);
            }

            agents = new Transform[Populations[populationIndex]];
            for (int index = 0; index < agents.Length; index++)
            {
                GameObject npc = GameObject.CreatePrimitive(PrimitiveType.Cube);
                npc.name = "NPC " + index.ToString(Invariant);
                npc.transform.SetParent(transform, false);
                npc.transform.position = new Vector3(index % 32 - 15.5f, 0f, index / 32 - 15.5f);
                npc.transform.localScale = Vector3.one * 0.4f;
                Destroy(npc.GetComponent<BoxCollider>());
                agents[index] = npc.transform;
            }
            frameIndex = 0;
            pendingSample = false;
            startedAt = Time.realtimeSinceStartupAsDouble;
        }

        private void Update()
        {
            float delta = Time.unscaledDeltaTime;
            if (pendingSample && delta > 0f)
                samples.Add(new Sample
                {
                    NpcCount = agents.Length,
                    FrameIndex = frameIndex++,
                    FrameMs = delta * 1000.0,
                    WorkloadMs = previousWorkloadMs
                });

            double elapsed = Time.realtimeSinceStartupAsDouble - startedAt;
            if (elapsed >= WarmupSeconds + SampleSeconds)
            {
                if (frameIndex == 0)
                {
                    Debug.LogError("SpecTuner has no recorded frames for this scenario. Keep Play mode active and rerun.");
                    enabled = false;
                    return;
                }
                populationIndex++;
                if (populationIndex == Populations.Length)
                {
                    try
                    {
                        WriteCapture();
                    }
                    finally
                    {
                        enabled = false;
                    }
                }
                else
                {
                    BeginScenario();
                }
                return;
            }

            long started = Stopwatch.GetTimestamp();
            using (WorkloadMarker.Auto())
                NpcWorkload.Tick(agents, waypoints, delta);
            previousWorkloadMs = (Stopwatch.GetTimestamp() - started) * 1000.0 / Stopwatch.Frequency;
            pendingSample = elapsed >= WarmupSeconds;
        }

        private void WriteCapture()
        {
            string directory = Path.Combine(Application.persistentDataPath, "SpecTuner");
            Directory.CreateDirectory(directory);
            string filename = "unity-" + DateTime.UtcNow.ToString("yyyyMMdd-HHmmss", Invariant)
                + "-" + Guid.NewGuid().ToString("N");
            string path = Path.Combine(directory, filename + ".csv");
            string temporaryPath = Path.Combine(directory, filename + ".tmp");
            string mode = Application.isEditor ? "editor" : "player";
            string mvid = typeof(NpcWorkload).Module.ModuleVersionId.ToString("D");
            using (var writer = new StreamWriter(temporaryPath))
            {
                writer.WriteLine("scenario,npc_count,frame_index,frame_ms,fps,workload_ms,run_mode,assembly_mvid");
                foreach (Sample sample in samples)
                    writer.WriteLine(string.Format(Invariant,
                        "npc-scan,{0},{1},{2:R},{3:R},{4:R},{5},{6}",
                        sample.NpcCount, sample.FrameIndex, sample.FrameMs,
                        1000.0 / sample.FrameMs, sample.WorkloadMs, mode, mvid));
            }
            File.Move(temporaryPath, path);
            Debug.Log("SpecTuner capture written to " + path);
        }

        private void OnDisable()
        {
            if (!settingsApplied)
                return;
            QualitySettings.vSyncCount = previousVsync;
            Application.targetFrameRate = previousTargetFps;
            settingsApplied = false;
        }
    }
}
