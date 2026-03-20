import argparse
import json
import os
from ultralytics import YOLO
from datetime import datetime

def run_experiment(project, config_path):
    project_dir = os.path.join("projects", project)

    # Resolve config path relative to project if not absolute
    if not os.path.isabs(config_path):
        config_path = os.path.join(project_dir, config_path)

    with open(config_path, 'r') as f:
        config = json.load(f)

    exp_name = config["experiment_name"]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    exp_dir = os.path.join(project_dir, "experiments", f"{exp_name}_{timestamp}")

    os.makedirs(exp_dir, exist_ok=True)

    # Save config snapshot (CRITICAL)
    with open(os.path.join(exp_dir, "config.json"), "w") as f:
        json.dump(config, f, indent=4)

    # Load model
    model = YOLO(config["model"])

    # Resolve dataset path relative to project
    dataset_path = os.path.join(project_dir, config["dataset_path"])

    # Train
    results = model.train(
        data=os.path.join(dataset_path, "data.yaml"),
        epochs=config["epochs"],
        imgsz=config["imgsz"],
        batch=config["batch"],
        project=exp_dir,
        name="train"
    )

    # Log metrics
    metrics = {
        "mAP50": results.results_dict.get("metrics/mAP50(B)", None),
        "mAP50-95": results.results_dict.get("metrics/mAP50-95(B)", None)
    }
    with open(os.path.join(exp_dir, "results.json"), "w") as f:
        json.dump(metrics, f, indent=4)

    print(f"✅ Experiment complete: {exp_dir}")
    print(f"   mAP50: {metrics['mAP50']}  |  mAP50-95: {metrics['mAP50-95']}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="svs_plumbing")
    parser.add_argument("--config", default="configs/train_config_v1.json")
    args = parser.parse_args()
    run_experiment(args.project, args.config)
