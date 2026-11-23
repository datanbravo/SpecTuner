using System;
using Unity.Profiling;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace SpecTuner.UnityDemo
{
    public static class WaypointChecks
    {
        [MenuItem("SpecTuner/Run Waypoint Equivalence Checks")]
        public static void RunAll()
        {
            CheckSelection("first tie wins", 0, Vector3.right, Vector3.left);
            CheckSelection("duplicate waypoints", 1, Vector3.right * 2, Vector3.right, Vector3.right);
            CheckSelection("arrival threshold is inclusive", 2,
                Vector3.right * 0.0999f, Vector3.right * 0.1f, Vector3.right * 0.1001f);
            CheckSelection("nearest eligible wins", 2, Vector3.right, Vector3.right * 0.1f, Vector3.up * 0.2f);
            CheckSelection("all ineligible falls back to zero", 0, Vector3.right * 0.1f, Vector3.zero);
            CheckSelection("single waypoint", 0, Vector3.forward);
            CheckSelection("empty selector fallback", 0);
            CheckSeededTrajectories();
            CheckSelectorAllocations();
            Debug.Log("SpecTuner waypoint checks passed: 7 edge cases and 128 seeded movement ticks.");
        }

        public static void RunBatch()
        {
            try
            {
                RunAll();
                EditorApplication.Exit(0);
            }
            catch (Exception error)
            {
                Debug.LogException(error);
                EditorApplication.Exit(1);
            }
        }

        private static void CheckSelection(string name, int expected, params Vector3[] waypoints)
        {
            int baseline = NpcWorkload.SelectWaypoint(Vector3.zero, waypoints, WaypointSearchMode.Baseline);
            int optimized = NpcWorkload.SelectWaypoint(Vector3.zero, waypoints, WaypointSearchMode.Optimized);
            if (baseline != expected || optimized != expected)
                throw new InvalidOperationException($"{name}: expected {expected}, got {baseline} and {optimized}");
        }

        private static void CheckSeededTrajectories()
        {
            var random = new System.Random(3817);
            var waypoints = new Vector3[128];
            for (int index = 0; index < waypoints.Length; index++)
                waypoints[index] = NextPoint(random);
            var baseline = new Transform[8];
            var optimized = new Transform[baseline.Length];
            float[] deltas = { 0f, 1f / 60f, 1f / 30f, 0.5f };
            try
            {
                for (int index = 0; index < baseline.Length; index++)
                {
                    Vector3 start = NextPoint(random);
                    baseline[index] = new GameObject().transform;
                    optimized[index] = new GameObject().transform;
                    baseline[index].position = start;
                    optimized[index].position = start;
                }
                for (int tick = 0; tick < 128; tick++)
                {
                    for (int index = 0; index < baseline.Length; index++)
                    {
                        int before = NpcWorkload.SelectWaypoint(baseline[index].position, waypoints, WaypointSearchMode.Baseline);
                        int after = NpcWorkload.SelectWaypoint(optimized[index].position, waypoints, WaypointSearchMode.Optimized);
                        if (before != after)
                            throw new InvalidOperationException($"Waypoint differs at tick {tick}, NPC {index}");
                    }
                    float delta = deltas[tick % deltas.Length];
                    NpcWorkload.Tick(baseline, waypoints, delta, WaypointSearchMode.Baseline);
                    NpcWorkload.Tick(optimized, waypoints, delta, WaypointSearchMode.Optimized);
                    for (int index = 0; index < baseline.Length; index++)
                        if (!baseline[index].position.Equals(optimized[index].position))
                            throw new InvalidOperationException($"Position differs at tick {tick}, NPC {index}");
                }
            }
            finally
            {
                foreach (Transform agent in baseline)
                    if (agent != null)
                        Object.DestroyImmediate(agent.gameObject);
                foreach (Transform agent in optimized)
                    if (agent != null)
                        Object.DestroyImmediate(agent.gameObject);
            }
        }

        private static Vector3 NextPoint(System.Random random)
        {
            return new Vector3(random.Next(-180, 181) / 10f, 0f, random.Next(-180, 181) / 10f);
        }

        private static void CheckSelectorAllocations()
        {
            using var frameRecorder = BenchmarkRunner.StartFrameAllocationRecorder();
            Debug.Log(frameRecorder.Valid
                ? "SpecTuner frame managed-byte counter available."
                : "SpecTuner frame managed-byte counter unavailable.");
            using var recorder = new ProfilerRecorder(ProfilerCategory.Internal, "GC.Alloc", 1,
                ProfilerRecorderOptions.CollectOnlyOnCurrentThread |
                ProfilerRecorderOptions.SumAllSamplesInFrame |
                ProfilerRecorderOptions.WrapAroundWhenCapacityReached);
            if (!recorder.Valid)
            {
                Debug.Log("SpecTuner selector allocation check skipped: counter unavailable.");
                return;
            }

            var waypoints = new Vector3[128];
            NpcWorkload.SelectWaypoint(Vector3.zero, waypoints, WaypointSearchMode.Baseline);
            NpcWorkload.SelectWaypoint(Vector3.zero, waypoints, WaypointSearchMode.Optimized);
            recorder.Start();
            NpcWorkload.SelectWaypoint(Vector3.zero, waypoints, WaypointSearchMode.Baseline);
            recorder.Stop();
            long baselineCount = recorder.Count > 0 ? recorder.GetSample(0).Count : 0;
            recorder.Reset();
            recorder.Start();
            NpcWorkload.SelectWaypoint(Vector3.zero, waypoints, WaypointSearchMode.Optimized);
            recorder.Stop();
            long optimizedCount = recorder.Count > 0 ? recorder.GetSample(0).Count : 0;
            if (baselineCount < 1 || optimizedCount != 0)
                throw new InvalidOperationException("Waypoint selector allocation check failed.");
            Debug.Log("SpecTuner selector allocation check passed.");
        }
    }
}
