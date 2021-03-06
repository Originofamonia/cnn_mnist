from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
import os

# Imports
import numpy as np
import tensorflow as tf

tf.logging.set_verbosity(tf.logging.INFO)

IMAGE_SIZE = 128
learning_rate = 1e-3
batch_size = 100
steps = 1e4


# image object from protobuf
class ImageObject:
    def __init__(self):
        self.image = tf.Variable([], dtype=tf.string)
        self.height = tf.Variable([], dtype=tf.int64)
        self.width = tf.Variable([], dtype=tf.int64)
        self.filename = tf.Variable([], dtype=tf.string)
        self.label = tf.Variable([], dtype=tf.int64)


def read_and_decode(filename_queue, is_train):
    imgs = []
    lbls = []
    reader = tf.TFRecordReader()
    _, serialized_example = reader.read(filename_queue)
    features = tf.parse_single_example(serialized_example, features={
        "image/encoded": tf.FixedLenFeature([], tf.string),
        "image/class/label": tf.FixedLenFeature([], tf.int64)})
    image_encoded = features["image/encoded"]
    image_raw = tf.image.decode_jpeg(image_encoded, channels=3)
    image_object = ImageObject()
    image_object.image = tf.image.resize_image_with_crop_or_pad(image_raw, IMAGE_SIZE, IMAGE_SIZE)
    image_object.label = tf.cast(features["image/class/label"], tf.int64)
    image_object.image = tf.reshape(image_object.image, [128 * 128 * 3])
    with tf.Session() as sess:
        sess.run(tf.local_variables_initializer())
        coord = tf.train.Coordinator()
        threads = tf.train.start_queue_runners(sess=sess, coord=coord)
        while not coord.should_stop():
            try:
                img, label = sess.run([image_object.image, image_object.label])
            except tf.errors.OutOfRangeError:
                print("Turn to next folder.")
                break
            imgs.append(img)
            lbls.append(label)
            if is_train is True and len(imgs) == 51840:  # should be 51840
                break
            elif is_train is False and len(lbls) == 6372:  # should be 9372, but at 1370000 sth the file was corrupted, so use 6372
                break

        coord.request_stop()
        coord.join(threads)
    return imgs, lbls


def read_data():
    # Load training and eval data
    mnist = tf.contrib.learn.datasets.load_dataset("mnist")
    train_data = mnist.train.images  # Returns np.array
    train_labels = np.asarray(mnist.train.labels, dtype=np.int32)
    eval_data = mnist.test.images  # Returns np.array
    eval_labels = np.asarray(mnist.test.labels, dtype=np.int32)
    return train_data, train_labels, eval_data, eval_labels


def read_tfrecords(filename, is_train):
    filename_queue = tf.train.string_input_producer([filename])
    image, label = read_and_decode(filename_queue, is_train)

    return np.asarray(image, dtype=np.float32), np.asarray(label, dtype=np.int32)


def read_tfrecords_v2(filename, num_of_images):
    imgs = []
    lbls = []
    filename_queue = tf.train.string_input_producer([filename])  # 读入流中
    reader = tf.TFRecordReader()
    _, serialized_example = reader.read(filename_queue)  # 返回文件名和文件
    features = tf.parse_single_example(
        serialized_example,
        features={
            'label': tf.FixedLenFeature([], tf.int64),
            'img_raw': tf.FixedLenFeature([], tf.string)
        }
    )  # 将image数据和label取出来

    image = tf.decode_raw(features['img_raw'], tf.uint8)
    image = tf.reshape(image, [-1])
    label = tf.cast(features['label'], tf.int32)
    with tf.Session() as sess:
        init_op = tf.global_variables_initializer()
        sess.run(init_op)
        coord = tf.train.Coordinator()
        threads = tf.train.start_queue_runners(coord=coord)
        for i in range(num_of_images):
            example, lbl = sess.run([image, label])
            imgs.append(example)
            lbls.append(lbl)
        coord.request_stop()
        coord.join(threads)

    return np.float32(imgs), np.int32(lbls)


def cnn_model_fn(features, labels, mode):
    """Model function for CNN."""
    # Input layer
    input_layer = tf.reshape(features["x"], [-1, 128, 128, 3])

    # Convolutional layer #1
    conv1 = tf.layers.conv2d(
        inputs=input_layer,
        filters=32,
        kernel_size=[5, 5],
        strides=2,
        padding='valid',
        activation=tf.nn.relu
    )

    # Pooling layer #1
    pool1 = tf.layers.max_pooling2d(inputs=conv1, pool_size=[2, 2], strides=2)

    # Convolutional layer #2 and pooling layer #2
    conv2 = tf.layers.conv2d(
        inputs=pool1,
        filters=64,
        strides=2,
        kernel_size=[5, 5],
        padding='same',
        activation=tf.nn.relu
    )
    pool2 = tf.layers.max_pooling2d(inputs=conv2, pool_size=[2, 2], strides=2)

    # Dense layer
    pool2_flat = tf.reshape(pool2, [-1, 8 * 8 * 64])
    dense = tf.layers.dense(inputs=pool2_flat, units=1024, activation=tf.nn.relu)
    dropout = tf.layers.dropout(inputs=dense, rate=0.4, training=mode == tf.estimator.ModeKeys.TRAIN)

    # Logits layer
    logits = tf.layers.dense(inputs=dropout, units=10)

    predictions = {
        # Generate predictions (for PREDICT and EVAL mode)
        "classes": tf.argmax(input=logits, axis=1),
        # Add 'softmax_tensor' to the graph. It is used for PREDICT and by the 'logging_hook'
        "probabilities": tf.nn.softmax(logits, name="softmax_tensor")
    }

    if mode == tf.estimator.ModeKeys.PREDICT:
        return tf.estimator.EstimatorSpec(mode=mode, predictions=predictions)

    # Calculate loss (for both TRAIN and EVAL mode)
    onehot_labels = tf.one_hot(indices=labels, depth=10)
    loss = tf.losses.softmax_cross_entropy(onehot_labels=onehot_labels, logits=logits)

    # Configure the Training Op (for TRAIN mode)
    if mode == tf.estimator.ModeKeys.TRAIN:
        optimizer = tf.train.GradientDescentOptimizer(learning_rate=learning_rate)
        train_op = optimizer.minimize(
            loss=loss,
            global_step=tf.train.get_global_step()
        )
        return tf.estimator.EstimatorSpec(mode=mode, loss=loss, train_op=train_op)

    # Add evaluation metrices (for EVAL mode)
    eval_metric_ops = {
        "accuracy": tf.metrics.accuracy(
            labels=labels, predictions=predictions["classes"])
    }
    return tf.estimator.EstimatorSpec(mode=mode, loss=loss, eval_metric_ops=eval_metric_ops)


def main(unused_argv):
    train_tfrecord = './dataset-128/train_3ch.tfrecords'
    eval_tfrecord = './dataset-128/eval_3ch.tfrecords'
    eval_data, eval_labels = read_tfrecords_v2(eval_tfrecord, num_of_images=3000)  # should be 3000
    train_data, train_labels = read_tfrecords_v2(train_tfrecord, num_of_images=14280)  # should be 17280

    # Create the estimator
    cnn_classifier = tf.estimator.Estimator(
        model_fn=cnn_model_fn, model_dir="./model-3ch/"
    )

    # Set up logging for predictions
    tensors_to_log = {"probabilities": "softmax_tensor"}
    logging_hook = tf.train.LoggingTensorHook(
        tensors=tensors_to_log, every_n_iter=50)

    # Train the model
    train_input_fn = tf.estimator.inputs.numpy_input_fn(
        x={"x": train_data},
        y=train_labels,
        batch_size=batch_size,  # was 100
        num_epochs=None,
        shuffle=True
    )
    cnn_classifier.train(
        input_fn=train_input_fn,
        steps=steps,
        hooks=[logging_hook]
    )

    # Evaluate the model and print results
    eval_input_fn = tf.estimator.inputs.numpy_input_fn(
        x={"x": eval_data},
        y=eval_labels,
        num_epochs=1,
        shuffle=False
    )
    eval_results = cnn_classifier.evaluate(input_fn=eval_input_fn)
    print(eval_results)


if __name__ == "__main__":
    tf.app.run()
