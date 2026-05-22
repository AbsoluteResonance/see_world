SLAM_STATUS = {"status": "not_implemented", "message": "SLAM 模块尚未部署"}


def reconstruct(images_dir: str, output_dir: str) -> dict:
    return {**SLAM_STATUS, "images_dir": images_dir, "output_dir": output_dir}


def get_pose() -> dict:
    return {**SLAM_STATUS, "detail": "No pose data available"}


def get_pointcloud() -> dict:
    return {**SLAM_STATUS, "detail": "No pointcloud data available"}
