import glob
from hashlib import md5
import json
import os
import shutil
from subprocess import check_call
import zipfile


import numpy as np
from tqdm import tqdm

from ..datasets import FixationTrains, create_subset
from ..utils import (
    TemporaryDirectory,
    filter_files,
    download_and_check,
    atomic_directory_setup)

from .utils import create_stimuli, _load


condition_mapping = {
    'present': 1,
    'absent': 0
}


TASKS = ['bottle', 'bowl', 'car', 'chair', 'clock', 'cup', 'fork', 'keyboard', 'knife', 'laptop', 'microwave', 'mouse', 'oven', 'potted plant', 'sink', 'stop sign', 'toilet', 'tv']


def get_COCO_Search18(location=None, split=1):
    """
    Loads or downloads and caches the COCO Search18 dataset.

    The dataset consists of about 5317 images from MS COCO with
    scanpath data from 11 observers doing a visual search task
    for one of 18 different object categories.

    The COCO images have been rescaled and padded to a size of
    1680x1050 pixels.

    The scanpaths come with attributes for
    - (fixation) duration in seconds
    - task, i.e. search target. Check pysaliency.external_datasets.coco_search18.TASKS for label names.
    - target present (1) or target absent (0)
    - target_bbox: bounding box of target (x, y, width, height)
    - correct_response: whether the subject correctly responded
      whether the target is present or not
    - reaction time to response in seconds

    @type  location: string, defaults to `None`
    @param location: If and where to cache the dataset. The dataset
                     will be stored in the subdirectory `toronto` of
                     location and read from there, if already present.
    @return: Training stimuli, trainint FixationTrains, validation Stimuli, validation FixationTrains

    .. seealso::

        Chen, Y., Yang, Z., Ahn, S., Samaras, D., Hoai, M., & Zelinsky, G. (2021).
        COCO-Search18 Fixation Dataset for Predicting Goal-directed Attention Control.
        Scientific Reports, 11 (1), 1-11, 2021.
        https://www.nature.com/articles/s41598-021-87715-9

        Yang, Z., Huang, L., Chen, Y., Wei, Z., Ahn, S., Zelinsky, G., Samaras, D., & Hoai, M. (2020).
        Predicting Goal-directed Human Attention Using Inverse Reinforcement Learning.
        In Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (pp. 193-202).

        https://sites.google.com/view/cocosearch/home
    """
    if split != 1:
        raise NotImplementedError

    dataset_name = 'COCO-Search18'
    if location:
        location = os.path.join(location, dataset_name)
        if os.path.exists(location):
            stimuli_train = _load(os.path.join(location, 'stimuli_train.hdf5'))
            fixations_train = _load(os.path.join(location, 'fixations_train.hdf5'))
            stimuli_validation = _load(os.path.join(location, 'stimuli_validation.hdf5'))
            fixations_validation = _load(os.path.join(location, 'fixations_validation.hdf5'))
            return stimuli_train, fixations_train, stimuli_validation, fixations_validation
        os.makedirs(location)

    with atomic_directory_setup(location):
        with TemporaryDirectory(cleanup=True) as temp_dir:
            download_and_check('http://vision.cs.stonybrook.edu/~cvlab_download/COCOSearch18-images-TP.zip',
                               os.path.join(temp_dir, 'COCOSearch18-images-TP.zip'),
                               '4a815bb591cb463ab77e5ba0c68fedfb')

            download_and_check('http://vision.cs.stonybrook.edu/~cvlab_download/COCOSearch18-images-TA.zip',
                               os.path.join(temp_dir, 'COCOSearch18-images-TA.zip'),
                               '85af7d74fa57c202320fa5e7d0dcc187')

            download_and_check('https://saliency.tuebingen.ai/data/coco_search18_TP.zip',
                               os.path.join(temp_dir, 'coco_search18_TP.zip'),
                               'bfcf4c005a89c43a1719b28b028c5499')

            download_and_check('http://vision.cs.stonybrook.edu/~cvlab_download/COCOSearch18-fixations-TA.zip',
                               os.path.join(temp_dir, 'COCOSearch18-fixations-TA.zip'),
                               'e44befa2e1bb764c35dc910673b4ff20')


            # Stimuli
            print('Creating stimuli')
            f = zipfile.ZipFile(os.path.join(temp_dir, 'COCOSearch18-images-TP.zip'))
            namelist = f.namelist()
            namelist = filter_files(namelist, ['.svn', '__MACOSX', '.DS_Store'])
            f.extractall(temp_dir, namelist)

            f = zipfile.ZipFile(os.path.join(temp_dir, 'COCOSearch18-images-TA.zip'))
            namelist = f.namelist()
            namelist = filter_files(namelist, ['.svn', '__MACOSX', '.DS_Store'])
            f.extractall(temp_dir, namelist)

            # unifying images for different tasks

            stimulus_directory = os.path.join(temp_dir, 'stimuli')
            os.makedirs(stimulus_directory)

            filenames = []
            for filename in tqdm(
                    glob.glob(os.path.join(temp_dir, 'images', '*', '*.jpg'))
                    + glob.glob(os.path.join(temp_dir, 'coco_search18_images_TA', '*', '*.jpg'))
                ):
                basename = os.path.basename(filename)
                target_filename = os.path.join(stimulus_directory, basename)
                if os.path.isfile(target_filename):
                    with open(target_filename, 'rb') as old_file:
                        md5_previous = md5(old_file.read()).hexdigest()
                    with open(filename, 'rb') as new_file:
                        md5_new = md5(new_file.read()).hexdigest()
                    if md5_previous != md5_new:
                        raise ValueError("same image with different md5 sums! " + md5_previous + '!=' + md5_new)
                    continue

                shutil.copy(filename, target_filename)
                filenames.append(basename)
            filenames = sorted(filenames)

            stimuli_src_location = os.path.join(temp_dir, 'stimuli')
            stimuli_target_location = os.path.join(location, 'stimuli') if location else None
            stimuli_filenames = filenames
            stimuli = create_stimuli(stimuli_src_location, stimuli_filenames, stimuli_target_location)

            print('creating fixations')

            with zipfile.ZipFile(os.path.join(temp_dir, 'coco_search18_TP.zip')) as tp_fixations:
                json_data_tp_train = json.loads(tp_fixations.read('coco_search18_fixations_TP_train_split1.json'))
                json_data_tp_val = json.loads(tp_fixations.read('coco_search18_fixations_TP_validation_split1.json'))

            with zipfile.ZipFile(os.path.join(temp_dir, 'COCOSearch18-fixations-TA.zip')) as tp_fixations:
                json_data_ta = json.loads(tp_fixations.read('coco_search18_fixations_TA/coco_search18_fixations_TA_trainval.json'))

            all_scanpaths = _get_COCO_Search18_fixations(json_data_tp_train + json_data_tp_val + json_data_ta, filenames)

            scanpaths_train = all_scanpaths.filter_fixation_trains(all_scanpaths.scanpath_attributes['split'] == 'train')
            scanpaths_validation = all_scanpaths.filter_fixation_trains(all_scanpaths.scanpath_attributes['split'] == 'valid')

            del scanpaths_train.scanpath_attributes['split']
            del scanpaths_validation.scanpath_attributes['split']

            ns_train = sorted(set(scanpaths_train.n))
            stimuli_train, fixations_train = create_subset(stimuli, scanpaths_train, ns_train)

            ns_val = sorted(set(scanpaths_validation.n))
            stimuli_val, fixations_val = create_subset(stimuli, scanpaths_validation, ns_val)

        if location:
            stimuli_train.to_hdf5(os.path.join(location, 'stimuli_train.hdf5'))
            fixations_train.to_hdf5(os.path.join(location, 'fixations_train.hdf5'))
            stimuli_val.to_hdf5(os.path.join(location, 'stimuli_validation.hdf5'))
            fixations_val.to_hdf5(os.path.join(location, 'fixations_validation.hdf5'))

    return stimuli_train, fixations_train, stimuli_val, fixations_val


def get_COCO_Search18_train(location=None, split=1):
    stimuli_train, fixations_train, stimuli_val, fixations_val = get_COCO_Search18(location=location, split=split)
    return stimuli_train, fixations_train


def get_COCO_Search18_validation(location=None, split=1):
    stimuli_train, fixations_train, stimuli_val, fixations_val = get_COCO_Search18(location=location, split=split)
    return stimuli_val, fixations_val


def _get_COCO_Search18_fixations(json_data, filenames):
    train_xs = []
    train_ys = []
    train_ts = []
    train_ns = []
    train_subjects = []
    train_tasks = []
    train_durations = []
    target_present = []
    target_bbox = []
    #fixOnTarget = []
    correct_response = []
    reaction_time = []
    split = []

    for item in tqdm(json_data):
        filename = item['name']
        n = filenames.index(filename)

        train_xs.append(item['X'])
        train_ys.append(item['Y'])
        train_ts.append(np.arange(item['length']))
        train_ns.append(n)
        train_subjects.append(item['subject'])
        train_durations.append(np.array(item['T']) / 1000)
        train_tasks.append(TASKS.index(item['task']))
        if 'bbox' in item:
            target_bbox.append(item['bbox'])
        else:
            target_bbox.append(np.full(4, np.nan))
        target_present.append(condition_mapping[item['condition']])
        correct_response.append(item['correct'])
        #reaction_time.append(item['RT'] if 'RT' in item else np.nan)
        reaction_time.append(item['RT'] / 1000.0 if 'RT' in item else np.nan)
        split.append(item['split'])

    scanpath_attributes = {
        'task': train_tasks,
        'target_present': target_present,
        'target_bbox': target_bbox,
        'correct_response': correct_response,
        'reaction_time': reaction_time,
        'split': split,
    }
    scanpath_fixation_attributes = {
        'durations': train_durations,
    }
    scanpath_attribute_mapping = {
        'durations': 'duration'
    }
    fixations = FixationTrains.from_fixation_trains(
        train_xs,
        train_ys,
        train_ts,
        train_ns,
        train_subjects,
        scanpath_attributes=scanpath_attributes,
        scanpath_fixation_attributes=scanpath_fixation_attributes,
        scanpath_attribute_mapping=scanpath_attribute_mapping,
    )

    return fixations