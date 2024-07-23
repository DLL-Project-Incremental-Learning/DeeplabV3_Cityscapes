import subprocess
import json
import logging
import os

logging.basicConfig(level=logging.INFO)

def objective_function():

    # Run the pipeline command
    pipeline_command = [
        "python", "./src/pipeline_ordered_buckets.py",
        "./configs/training_pipeline.json"
    ]
    logging.info(f"Running pipeline command: {' '.join(pipeline_command)}")
    try:
        subprocess.run(pipeline_command, check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Pipeline command failed: {e}")
        return {"fitness": float("-inf"), "cost": 1}
    
    # Run the test command
    test_command = [
        "python", "./tests/test_v6.py",
        "./configs/testing_pipeline.json"
    ]
    logging.info(f"Running test command: {' '.join(test_command)}")
    try:
        subprocess.run(test_command, check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Test command failed: {e}")
        return {"fitness": float("-inf"), "cost": 1}
    
    # Read the results
    result_path = 'checkpoints/validation_results_bn.json'
    if not os.path.exists(result_path):
        logging.error(f"Result file not found: {result_path}")
        return {"fitness": float("-inf"), "cost": 1}

    try:
        with open(result_path, 'r') as f:
            data = json.load(f)
        city_mIoU = data[2]['checkpoints'][0]["metrics_val"]['Mean IoU']
        kitti_mIoU = data[2]['checkpoints'][1]["metrics_val"]['Mean IoU']
        average_mIoU = (city_mIoU + kitti_mIoU) / 2
    except (json.JSONDecodeError, KeyError) as e:
        logging.error(f"Error reading mIoU from result file: {e}")
        return {"fitness": float("-inf"), "cost": 1}

    logging.info(f"Cityscapes mIoU: {city_mIoU}")
    logging.info(f"Kitti mIoU: {kitti_mIoU}")
    logging.info(f"Average mIoU: {average_mIoU}")

    print("Cityscapes mIoU:", city_mIoU)
    print("Kitti mIoU:", kitti_mIoU)
    print("Average mIoU:", average_mIoU)


    print("================================================================================\n\n")
    return {"fitness": -average_mIoU, "cost": 1}

if __name__ == "__main__":
    objective_function()