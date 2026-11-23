using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace SpecTuner.UnityDemo
{
    internal static class BenchmarkScene
    {
        private const string ScenePath = "Assets/Generated/Benchmark.unity";

        [MenuItem("SpecTuner/Open Benchmark Scene")]
        private static void Open()
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode ||
                !EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo())
                return;

            if (AssetDatabase.LoadAssetAtPath<SceneAsset>(ScenePath) != null)
            {
                EditorSceneManager.OpenScene(ScenePath);
                return;
            }

            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            if (!AssetDatabase.IsValidFolder("Assets/Generated"))
                AssetDatabase.CreateFolder("Assets", "Generated");

            Camera camera = new GameObject("Benchmark Camera").AddComponent<Camera>();
            camera.transform.position = new Vector3(0f, 35f, 0f);
            camera.transform.rotation = Quaternion.Euler(90f, 0f, 0f);
            camera.orthographic = true;
            camera.orthographicSize = 20f;
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.12f, 0.16f, 0.20f);

            Light light = new GameObject("Benchmark Light").AddComponent<Light>();
            light.type = LightType.Directional;
            light.transform.rotation = Quaternion.Euler(65f, -30f, 0f);
            new GameObject("SpecTuner Benchmark").AddComponent<BenchmarkRunner>();
            EditorSceneManager.SaveScene(scene, ScenePath);
        }
    }
}
