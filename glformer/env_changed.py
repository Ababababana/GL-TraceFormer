import logging
import os
import pickle
import random
from copy import deepcopy
import numpy as np
from efg.data.datasets.waymo import WaymoDetectionDataset
from efg.data.registry import DATASETS
from efg.data.augmentations import build_processors
from efg.data.datasets.waymo.utils import read_single_waymo, read_single_waymo_sweep
import re
from torchvision import transforms
from PIL import Image
import tensorflow as tf 

logger = logging.getLogger(__name__)


@DATASETS.register()
class CustomWDDataset(WaymoDetectionDataset):
    def __init__(self, config):
        super(CustomWDDataset, self).__init__(config)

        self.config = config
         
        #zjc
        self.img_data=False
        if self.config.projection != None:
            self.img_data=True
            self._img_trans=transforms.ToTensor()
                 
    
        self.is_train = config.task == "train"
        if self.is_train:
            boxes_path = config.dataset.train_boxes_path
            #boxes2d_path=config.dataset.train_boxes2d_path
        else:
            boxes_path = config.dataset.val_boxes_path
            #boxes2d_path = config.dataset.val_boxes2d_path
        self._boxes_path = boxes_path
        #self._boxes2d_path = boxes2d_path

        self.max_roi_num = config.dataset.max_roi_num
        self.traj_length = config.dataset.traj_length
        self.score_thresh = self.config.dataset.score_thresh
        logger.info(f"Using {self.nsweeps} sweep(s)")
        self.num_point_features = (
            len(config.dataset.format)
            if self.nsweeps == 1
            else len(config.dataset.format) + 1
        )

        self.transforms = build_processors(
            config.dataset.processors[config.task],
        )
        logger.info(f"Building data processors: {self.transforms}")

        self.boxes_dicts = self.load_boxes()

    def reset(self):
        random.shuffle(self.dataset_dicts)

    def load_boxes(self):
       
        with open(self._boxes_path, "rb") as f:
            boxes_all = pickle.load(f)
        if isinstance(boxes_all, dict):
            boxes_all_list = []
            for key in list(boxes_all.keys()):
                boxes_all_list.append(boxes_all[key])
            return boxes_all_list[:: self.load_interval]

        return boxes_all[:: self.load_interval]

    def transform_prebox_to_current_vel(self, pred_boxes3d, pose_pre, pose_cur, idx):
        pose_pre=pose_pre.reshape(4,4)
        pose_cur=pose_cur.reshape(4,4)
        expand_bboxes = np.concatenate(
            [pred_boxes3d[:, :3], np.ones((pred_boxes3d.shape[0], 1))], axis=-1
        )
        expand_vels = np.concatenate(
            [pred_boxes3d[:, 6:8], np.zeros((pred_boxes3d.shape[0], 1))], axis=-1
        )
        bboxes_global = np.dot(expand_bboxes, pose_pre.T)[:, :3]
        vels_global = np.dot(expand_vels, pose_pre[:3, :3].T)
        moved_bboxes_global = deepcopy(bboxes_global)
        time_lag = idx * 0.1
        moved_bboxes_global[:, :2] = (
            moved_bboxes_global[:, :2] + time_lag * vels_global[:, :2]
        )
        expand_bboxes_global = np.concatenate(
            [moved_bboxes_global[:, :3], np.ones((bboxes_global.shape[0], 1))], axis=-1
        )
        bboxes_pre2cur = np.dot(expand_bboxes_global, np.linalg.inv(pose_cur.T))[:, :3]
        vels_pre2cur = np.dot(vels_global, np.linalg.inv(pose_cur[:3, :3].T))[:, :2]
        bboxes_pre2cur = np.concatenate(
            [bboxes_pre2cur, pred_boxes3d[:, 3:6], vels_pre2cur, pred_boxes3d[:, 8:]],
            axis=-1,
        )
        bboxes_pre2cur[..., 8] = bboxes_pre2cur[..., 8] + np.arctan2(
            pose_pre[..., 1, 0], pose_pre[..., 0, 0]
        )
        bboxes_pre2cur[..., 8] = bboxes_pre2cur[..., 8] - np.arctan2(
            pose_cur[..., 1, 0], pose_cur[..., 0, 0]
        )

        return bboxes_pre2cur

    @staticmethod
    def reorder_rois_for_refining(pred_bboxes):
        num_max_rois = max([len(bbox) for bbox in pred_bboxes])
        num_max_rois = max(1, num_max_rois)  # at least one faked rois to avoid error
        ordered_bboxes = np.zeros(
            [len(pred_bboxes), num_max_rois, pred_bboxes[0].shape[-1]]
        )
    
        valid_mask = np.zeros(
            [len(pred_bboxes), num_max_rois, pred_bboxes[0].shape[-1]]
        )
        for bs_idx in range(ordered_bboxes.shape[0]):
            ordered_bboxes[bs_idx, : len(pred_bboxes[bs_idx])] = pred_bboxes[bs_idx]
            
            valid_mask[bs_idx, : len(pred_bboxes[bs_idx])] = 1
        return ordered_bboxes, valid_mask.astype(bool)

    def __getitem__(self, idx):
        #import pdb;pdb.set_trace()
        if not hasattr(self, "boxes_dicts"):
            self.boxes_dicts = self.load_boxes()
        info = deepcopy(self.dataset_dicts[idx])

        if "data/Waymo/" in info["path"]:
            info["path"] = info["path"].replace("data/Waymo/", "")
        if not os.path.isabs(info["path"]):
            info["path"] = os.path.join(self.root_path, info["path"])
        with open(info["path"], "rb") as f:
            obj = pickle.load(f)

        points = read_single_waymo(obj)
        '''
        #zjc
        if self.img_data:
            img_path= re.sub(r"\blidar\b","image",info["path"])
            ann_path= re.sub(r"\blidar\b","img_annos",info["path"])
            with open(img_path,"rb") as f:
                img_data=pickle.load(f) 
            img_list=[]
            for img_bytes in img_data["images"]:       
                img_pl=Image.open(img_bytes)
                img_list.append(np.array(img_pl))
            
            with open(ann_path,"rb") as f:
                img_anno=pickle.load(f)
            img_anno=np.array(img_anno)
        '''

        #zjc
        if self.img_data:
            img_path= re.sub(r"\blidar\b","image",info["path"])
            #ann_path= re.sub(r"\blidar\b","img_annos",info["path"])
            with open(img_path,"rb") as f:
                img_data=pickle.load(f)
            img_list=[]
            calibrations = img_data["calibrations"]
            poses        = img_data["frame_pose"]
            for img_bytes in img_data["images"]:
                img_pl=tf.image.decode_jpeg(img_bytes)
                img_list.append(self._img_trans(img_pl.numpy()))

    
        nsweeps = self.nsweeps
        if nsweeps > 1:
            sweep_points_list = [points]
            sweep_times_list = [np.zeros((points.shape[0], 1))]
            if self.img_data:
                sweep_imgs_list=[img_list]

            for i in range(nsweeps - 1):
                sweep = info["sweeps"][i]
                if "data/Waymo/" in sweep["path"]:
                    sweep["path"] = sweep["path"].replace("data/Waymo/", "")
                if not os.path.isabs(sweep["path"]):
                    sweep["path"] = os.path.join(self.root_path, sweep["path"])
                with open(sweep["path"], "rb") as f:
                    sweep_obj = pickle.load(f)
                '''
                #zjc
                if self.img_data:
                    sweep_img_path= re.sub(r"\blidar\b","image",sweep["path"])
                    #sweep_ann_path= re.sub(r"\blidar\b","img_annos",sweep["path"])
                    with open(sweep_img_path,"rb") as f:
                        sweep_img_data=pickle.load(f) 
                    sweep_imgs=[]
                    for sweep_img_bytes in sweep_img_data["images"]:       
                        sweep_img_pl=tf.image.decode_jpeg(sweep_img_bytes)
                        sweep_imgs.append(self._img_trans(sweep_img_pl.numpy()))
         
                    sweep_imgs_list.append(sweep_imgs) #List [ List[ Tensor[3,h,w] ] * 5 ] *nsweeps
                '''         

                points_sweep, times_sweep = read_single_waymo_sweep(sweep, sweep_obj)
                sweep_points_list.append(points_sweep)
                sweep_times_list.append(times_sweep)

            points = np.concatenate(sweep_points_list, axis=0)
            times = np.concatenate(sweep_times_list, axis=0).astype(points.dtype)

            points = np.hstack([points, times])
            if self.img_data:
               images = img_list 

        frame_id = int(info["token"].split("_frame_")[-1].split(".")[0])
        boxes_cur = deepcopy(self.boxes_dicts[idx])
        #boxes2d_cur = deepcopy(self.boxes2d_dicts[idx])
        #boxes2d_cur=np.stack(boxes2d_cur,axis=0).transpose(1,0,2)

        if not self.is_train:
            if "centerpoint" in self.config.dataset.val_boxes_path:
                labels = boxes_cur["pred_labels"].numpy()
                boxes3d = boxes_cur["pred_boxes3d"].numpy()
                boxes3d[:, -1] = -boxes3d[:, -1] - np.pi / 2
                boxes3d = boxes3d[:, [0, 1, 2, 4, 3, 5, -1]]
                vels_cur = boxes_cur["pred_vels"].numpy()
                scores_cur = boxes_cur["pred_scores"].numpy()
                labels_cur = labels + 1
            elif "mppnet" in self.config.dataset.val_boxes_path:
                labels = boxes_cur["pred_labels"]
                label_mask = labels >= 1
                boxes3d = boxes_cur["pred_boxes3d"][label_mask]
                #boxes2d = boxes2d_cur[label_mask]
                vels_cur = boxes_cur["pred_vels"][label_mask].reshape(-1, 2)
                scores_cur = boxes_cur["pred_scores"][label_mask]
                labels_cur = labels[label_mask]

            boxes3d_cur = np.concatenate(
                [
                    boxes3d[:, :6],
                    vels_cur,
                    boxes3d[:, -1:],
                    scores_cur[:, None],
                    labels_cur[:, None],
                ],
                -1,
            )
            boxes_all = []
            boxes_all.append(boxes3d_cur)
            
            #boxes2d_all = []
            #boxes2d_all.append(boxes2d)


        else:
            if "centerpoint" in self.config.dataset.train_boxes_path:
                labels = boxes_cur["pred_labels"].numpy()
                if self.score_thresh > 0:
                    label_mask = np.logical_and(
                        labels >= 0, (boxes_cur["pred_scores"] > self.score_thresh)
                    )
                else:
                    label_mask = labels >= 0
                boxes3d = boxes_cur["pred_boxes3d"][label_mask].numpy()
                boxes3d[:, -1] = -boxes3d[:, -1] - np.pi / 2
                boxes3d = boxes3d[:, [0, 1, 2, 4, 3, 5, -1]]
                vels_cur = boxes_cur["pred_vels"][label_mask].numpy()
                scores_cur = boxes_cur["pred_scores"][label_mask].numpy()
                labels_cur = labels[label_mask] + 1
            elif "mppnet" in self.config.dataset.train_boxes_path:
                labels = boxes_cur["pred_labels"]
                #labels2d = 
        
                if self.score_thresh > 0:
                    label_mask = np.logical_and(
                        labels >= 1, (boxes_cur["pred_scores"] > self.score_thresh)
                    )
                else:
                    label_mask = labels >= 1
                boxes3d = boxes_cur["pred_boxes3d"][label_mask]
                #boxes2d = boxes2d_cur[label_mask]

                vels_cur = boxes_cur["pred_vels"][label_mask]
                scores_cur = boxes_cur["pred_scores"][label_mask]
                labels_cur = labels[label_mask]

            if boxes3d.shape[0] > self.max_roi_num:
                choice = np.random.choice(
                    boxes3d.shape[0], self.max_roi_num, replace=False
                )
                boxes3d = boxes3d[choice]
                #boxes2d = boxes2d[choice]
                vels_cur = vels_cur[choice]
                scores_cur = scores_cur[choice]
                labels_cur = labels_cur[choice]

            boxes3d_cur = np.concatenate(
                [
                    boxes3d[:, :6],
                    vels_cur,
                    boxes3d[:, -1:],
                    scores_cur[:, None],
                    labels_cur[:, None],
                ],
                -1,
            )

            boxes_all = []
            boxes_all.append(boxes3d_cur)

            #boxes2d_all = []
            #boxes2d_all.append(boxes2d)


            if self.traj_length > 1:
                for i in range(1, self.traj_length):
                    if frame_id - i >= 0:
                        seq_pre_idx = idx - i
                    else:
                        seq_pre_idx = idx - (i - 1)
                    boxes_pre = deepcopy(self.boxes_dicts[seq_pre_idx])
                    #boxes2d_pre = deepcopy(self.boxes2d_dicts[seq_pre_idx])
                    #boxes2d_pre = np.stack(boxes2d_pre,axis=0).transpose(1,0,2)     

                    info_pre = deepcopy(self.dataset_dicts[seq_pre_idx])
                    if "centerpoint" in self.config.dataset.train_boxes_path:
                        labels = boxes_pre["pred_labels"].numpy()
                        if self.score_thresh > 0:
                            label_mask = np.logical_and(
                                labels >= 0,
                                (boxes_pre["pred_scores"].numpy() > self.score_thresh),
                            )
                        else:
                            label_mask = labels >= 0
                        boxes3d = boxes_pre["pred_boxes3d"][label_mask].numpy()
                        boxes3d[:, -1] = -boxes3d[:, -1] - np.pi / 2
                        boxes3d = boxes3d[:, [0, 1, 2, 4, 3, 5, -1]]
                        vels_pre = boxes_pre["pred_vels"][label_mask].numpy()
                        scores_pre = boxes_pre["pred_scores"][label_mask].numpy()
                        labels_pre = labels[label_mask] + 1
                    elif "mppnet" in self.config.dataset.train_boxes_path:
                        labels = boxes_pre["pred_labels"]
                        if self.score_thresh > 0:
                            label_mask = np.logical_and(
                                labels >= 1,
                                (boxes_pre["pred_scores"] > self.score_thresh),
                            )
                        else:
                            label_mask = labels >= 1
                        boxes3d = boxes_pre["pred_boxes3d"][label_mask]
                        #boxes2d = boxes2d_pre[label_mask]  
    
                        vels_pre = boxes_pre["pred_vels"][label_mask]
                        scores_pre = boxes_pre["pred_scores"][label_mask]
                        labels_pre = labels[label_mask]
                    if boxes3d.shape[0] > self.max_roi_num:
                        choice = np.random.choice(
                            boxes3d.shape[0], self.max_roi_num, replace=False
                        )
                        boxes3d = boxes3d[choice]
                        #boxes2d = boxes2d[choice]
                        vels_pre = vels_pre[choice]
                        scores_pre = scores_pre[choice]
                        labels_pre = labels_pre[choice]

                    boxes3d_pre = np.concatenate(
                        [
                            boxes3d[:, :6],
                            vels_pre,
                            boxes3d[:, -1:],
                            scores_pre[:, None],
                            labels_pre[:, None],
                        ],
                        -1,
                    )

                    if frame_id == 0:
                        time_step = 0
                    else:
                        time_step = 1
                    if i == 1:
                        pred_boxes_trans = self.transform_prebox_to_current_vel(
                            boxes3d_pre,
                            pose_pre=info_pre["veh_to_global"],
                            pose_cur=info["veh_to_global"],
                            idx=time_step,
                        )

                        boxes_all.append(pred_boxes_trans)

                    pred_boxes = self.transform_prebox_to_current_vel(
                        boxes3d_pre,
                        pose_pre=info_pre["veh_to_global"],
                        pose_cur=info["veh_to_global"],
                        idx=0,
                    )
                    if i == 1:
                        assert pred_boxes_trans.shape == pred_boxes.shape
                    boxes_all.append(pred_boxes)
                    #boxes2d_all.append(boxes2d)

        info["metadata"] = {
            "root_path": self.root_path,
            "token": info["token"],
            "num_point_features": self.num_point_features,
            "pose": info["veh_to_global"],
        }

        if self.config.task == "test":
            pred_boxes, _ = self.reorder_rois_for_refining(boxes_all)
            pred_boxes = pred_boxes.astype(np.float32).reshape(-1, pred_boxes.shape[-1])
            info["annotations"] = {
                "pred_boxes3d": pred_boxes[:, :9],
                "pred_scores": pred_boxes[:, 9],
                "pred_labels": pred_boxes[:, 10],
            }
            points, info = self._apply_transforms(points, info)
            return points, info

        pred_boxes,_ = self.reorder_rois_for_refining(boxes_all)
        pred_boxes = pred_boxes.astype(np.float32).reshape(-1, pred_boxes.shape[-1])
        #pred_boxes2d = pred_boxes2d.astype(np.float32).reshape(-1,5, pred_boxes2d.shape[-1])
        info["annotations"]["pred_boxes3d"] = pred_boxes[:, :9]
       
        info["annotations"]["pred_scores"] = pred_boxes[:, 9]
        info["annotations"]["pred_labels"] = pred_boxes[:, 10]
        target = info["annotations"]
        keep = (target["gt_names"][:, None] == self.class_names).any(axis=1)
        target["gt_boxes"] = target["gt_boxes"][keep]
        target["gt_names"] = target["gt_names"][keep]
        #target["gt_ids"] = target["name"][keep]
        target["difficulty"] = target["difficulty"][keep]
        target["num_points_in_gt"] = target["num_points_in_gt"][keep]

        points, info = self._apply_transforms(points, info)
        if self.img_data:
            points = [[{"points":points}],{"images":images,"calibrations":calibrations,"poses":poses}]
        else:
            points = [{"points": points}]

        self._add_class_labels_to_annos(info)

        '''
        #zjc
        if self.img_data:
            img_path= re.sub(r"\blidar\b","image",info["path"])
            ann_path= re.sub(r"\blidar\b","img_annos",info["path"])
            with open(img_path,"rb") as f:
                img_data=pickle.load(f) 
            img_list=[]
            for img_bytes in img_data["images"]:       
                img_pl=Image.open(img_bytes)
                img_list.append(self._img_trans(img_pl))
            
            with open(ann_path,"rb") as f:
                img_anno=pickle.load(f)
            img_anno=np.stack(img_anno,axis=0).transpose(1,0,2)

            points.append({"images":imags})   # List [ List[ Tensor[3,h,w] ]*5 ] * nsweeps
            info["annotations"].update({"pred_boxes2d":img_anno})
        '''

        return points, info
