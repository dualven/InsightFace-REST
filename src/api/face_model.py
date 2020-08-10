from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from scipy import misc
import sys
import os
import argparse
import tensorflow as tf
import numpy as np
import mxnet as mx
import random
import sklearn
from sklearn.decomposition import PCA
from easydict import EasyDict as edict

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'align'))
import detect_face

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'common'))
import face_preprocess
import cv2


def ch_dev(arg_params, aux_params, ctx):
    new_args = dict()
    new_auxs = dict()
    for k, v in arg_params.items():
        new_args[k] = v.as_in_context(ctx)
    for k, v in aux_params.items():
        new_auxs[k] = v.as_in_context(ctx)
    return new_args, new_auxs


def do_flip(data):
    for idx in range(data.shape[0]):
        data[idx, :, :] = np.fliplr(data[idx, :, :])


def reproject_bb(dets, scale):
    for i, bb in enumerate(dets):
            dets[i] = bb
            dets[i][0:4] = bb[0:4] / scale
    return dets

def reproject_points(dets, scale):
    for i, bb in enumerate(dets):
            dets[i] = bb / scale
    return dets


def resize(img,max_size=640):
    try:
        largest_size = sorted(img.shape[:2])[0]
        scale = max_size / largest_size
        if scale >= 1 or max_size==0:
            scale = 1
            return img, scale
        else:
            img_res = cv2.resize(img, (0, 0), fx=scale, fy=scale)
            return img_res, scale
    except:
        return None


class FaceModel:
    def __init__(self, args):
        model = edict()
        with tf.Graph().as_default():
            #config = tf.ConfigProto()
            #config = tf.compat.v1.ConfigProto

            #config.intra_op_parallelism_threads = 16
            #config.inter_op_parallelism_threads = 16

            #config.gpu_options.per_process_gpu_memory_fraction = 0.2
            gpu_options = tf.compat.v1.GPUOptions(per_process_gpu_memory_fraction=0.2)
            config=tf.compat.v1.ConfigProto(gpu_options=gpu_options)
            #sess = tf.Session(config=config)
            sess = tf.compat.v1.Session(config=config)
            with sess.as_default():
                self.pnet, self.rnet, self.onet = detect_face.create_mtcnn(sess, None)

        self.threshold = args.threshold
        self.det_minsize = 20
        # self.det_threshold = [0.4, 0.6, 0.6]
        self.det_threshold = [0.6, 0.7, 0.7]
        # self.det_factor = 0.9
        self.det_factor = 0.709
        _vec = args.image_size.split(',')
        assert len(_vec) == 2
        self.image_size = (int(_vec[0]), int(_vec[1]))
        _vec = args.model.split(',')
        assert len(_vec) == 2
        prefix = _vec[0]
        epoch = int(_vec[1])
        print('loading', prefix, epoch)
        self.model = edict()
        if args.gpu != -1:
            self.model.ctx = mx.gpu(args.gpu)
        else:
            self.model.ctx = mx.cpu()
        self.model.sym, self.model.arg_params, self.model.aux_params = mx.model.load_checkpoint(prefix, epoch)
        self.model.arg_params, self.model.aux_params = ch_dev(self.model.arg_params, self.model.aux_params,
                                                              self.model.ctx)
        all_layers = self.model.sym.get_internals()
        self.model.sym = all_layers['fc1_output']

    def get_aligned_face(self, img, force=False):
        bounding_boxes, points = detect_face.detect_face(img, self.det_minsize, self.pnet, self.rnet, self.onet,
                                                         self.det_threshold, self.det_factor)

        if bounding_boxes.shape[0] == 0 and force:
            print('force det', img.shape)
            bounding_boxes, points = detect_face.detect_face(img, self.det_minsize, self.pnet, self.rnet, self.onet,
                                                             [0.3, 0.3, 0.1], self.det_factor)
        if bounding_boxes.shape[0] == 0:
            return None
        bindex = 0
        nrof_faces = bounding_boxes.shape[0]
        det = bounding_boxes[:, 0:4]
        img_size = np.asarray(img.shape)[0:2]
        if nrof_faces > 1:
            bounding_box_size = (det[:, 2] - det[:, 0]) * (det[:, 3] - det[:, 1])
            img_center = img_size / 2
            offsets = np.vstack(
                [(det[:, 0] + det[:, 2]) / 2 - img_center[1], (det[:, 1] + det[:, 3]) / 2 - img_center[0]])
            offset_dist_squared = np.sum(np.power(offsets, 2.0), 0)
            bindex = np.argmax(bounding_box_size - offset_dist_squared * 2.0)  # some extra weight on the centering
        det = bounding_boxes[:, 0:4]
        det = det[bindex, :]
        points = points[:, bindex]
        landmark = points.reshape((2, 5)).T
        # points need to be transpose, points = points.reshape( (5,2) ).transpose()
        det = np.squeeze(det)
        bb = det
        points = list(points.flatten())
        assert (len(points) == 10)
        str_image_size = "%d,%d" % (self.image_size[0], self.image_size[1])
        warped = face_preprocess.preprocess(img, bbox=bb, landmark=landmark, image_size=str_image_size)
        warped = np.transpose(warped, (2, 0, 1))
        return warped

    def get_all_faces(self, img):
        str_image_size = "%d,%d" % (self.image_size[0], self.image_size[1])
        bounding_boxes, points = detect_face.detect_face(img, self.det_minsize, self.pnet, self.rnet, self.onet,
                                                         self.det_threshold, self.det_factor)
        ret = []
        for i in range(bounding_boxes.shape[0]):
            bbox = bounding_boxes[i, 0:4]
            landmark = points[:, i].reshape((2, 5)).T
            aligned = face_preprocess.preprocess(img, bbox=bbox, landmark=landmark, image_size=str_image_size)
            aligned = np.transpose(aligned, (2, 0, 1))
            ret.append(aligned)
        return ret

    def get_all_faces_bulk(self, imgs,max_size=640):
        str_image_size = "%d,%d" % (self.image_size[0], self.image_size[1])

        imgs_res = np.array([resize(img,max_size) for img in imgs])

        res = detect_face.bulk_detect_face(imgs_res[:, 0], self.det_minsize, self.pnet, self.rnet, self.onet,
                                           self.det_threshold, self.det_factor)

        output = []
        count = 0
        for idx in range(len(imgs)):
            im_output = []
            e = res[count]

            if e is not None:
                bounding_boxes, points = e
                bounding_boxes = reproject_bb(bounding_boxes, imgs_res[:, 1][idx])
                points = reproject_points(points, imgs_res[:, 1][idx])

                for i in range(bounding_boxes.shape[0]):
                    bbox = bounding_boxes[i, 0:4]
                    prob = bounding_boxes[i, 4]
                    landmark = points[:, i].reshape((2, 5)).T
                    aligned = face_preprocess.preprocess(imgs[idx], bbox=bbox, landmark=landmark,
                                                         image_size=str_image_size)
                    aligned = np.transpose(aligned, (2, 0, 1))
                    im_output.append(([aligned, (bbox, prob)]))
                output.append(im_output)
            else:
                output.append(None)

            count += 1

        return output

    def get_feature_impl(self, face_img, norm):
        embedding = None
        for flipid in [0, 1]:
            _img = np.copy(face_img)
            if flipid == 1:
                do_flip(_img)

            input_blob = np.expand_dims(_img, axis=0)
            self.model.arg_params["data"] = mx.nd.array(input_blob, self.model.ctx)
            self.model.arg_params["softmax_label"] = mx.nd.empty((1,), self.model.ctx)
            exe = self.model.sym.bind(self.model.ctx, self.model.arg_params, args_grad=None, grad_req="null",
                                      aux_states=self.model.aux_params)
            exe.forward(is_train=False)
            _embedding = exe.outputs[0].asnumpy()
            if embedding is None:
                embedding = _embedding
            else:
                embedding += _embedding
        if norm:
            embedding = sklearn.preprocessing.normalize(embedding)
        return embedding

    def get_feature_bulk(self, face_img, norm):
        embedding = None
        self.model.arg_params["data"] = mx.nd.array(face_img, self.model.ctx)
        self.model.arg_params["softmax_label"] = mx.nd.empty((1,), self.model.ctx)
        exe = self.model.sym.bind(self.model.ctx, self.model.arg_params, args_grad=None, grad_req="null",
                                  aux_states=self.model.aux_params)
        exe.forward(is_train=False)
        _embedding = exe.outputs[0].asnumpy()
        if embedding is None:
            embedding = _embedding
        else:
            embedding += _embedding
        if norm:
            embedding = sklearn.preprocessing.normalize(embedding)
        return embedding

    def get_feature(self, face_img, norm=True):
        # aligned_face = self.get_aligned_face(img, force)
        # if aligned_face is None:
        #  return None
        return self.get_feature_impl(face_img, norm)

    def is_same_id(self, source_img, target_img_list):
        source_face = self.get_aligned_face(source_img, True)
        print('source face', source_face.shape)
        target_face_list = []
        pp = 0
        for img in target_img_list:
            target_force = False
            if pp == len(target_img_list) - 1 and len(target_face_list) == 0:
                target_force = True
            target_face = self.get_aligned_face(img, target_force)
            if target_face is not None:
                target_face_list.append(target_face)
            pp += 1
        print('target face', len(target_face_list))
        source_feature = self.get_feature(source_face, True)
        target_feature = None
        for target_face in target_face_list:
            _feature = self.get_feature(target_face, False)
            if target_feature is None:
                target_feature = _feature
            else:
                target_feature += _feature
        target_feature = sklearn.preprocessing.normalize(target_feature)
        # sim = np.dot(source_feature, target_feature.T)
        diff = np.subtract(source_feature, target_feature)
        dist = np.sum(np.square(diff), 1)
        print('dist', dist)
        # print(sim, dist)
        if dist <= self.threshold:
            return True
        else:
            return False

    def sim(self, source_img, target_img_list):
        source_face = self.get_aligned_face(source_img, True)
        target_face_list = []
        pp = 0
        for img in target_img_list:
            target_force = False
            if pp == len(target_img_list) - 1 and len(target_face_list) == 0:
                target_force = True
            target_face = self.get_aligned_face(img, target_force)
            if target_face is not None:
                target_face_list.append(target_face)
            pp += 1
        source_feature = self.get_feature(source_face, True)
        target_feature = None
        sim_list = []
        for target_face in target_face_list:
            _feature = self.get_feature(target_face, True)
            _sim = (1. + np.dot(source_feature, _feature.T)) / 2.
            sim_list.append(float(_sim.flatten()[0]))
        return sim_list
