import os
import math
import numpy as np
import PIL.Image
import tensorflow as tf

tf.app.flags.DEFINE_string("model", "inception/tensorflow_inception_graph.pb", "Model")
tf.app.flags.DEFINE_string("input", "", "Input Image (JPG)");
tf.app.flags.DEFINE_string("output", "output", "Output prefix");
tf.app.flags.DEFINE_string("layer", "import/mixed4c", "Layer name");
tf.app.flags.DEFINE_integer("feature", "-1", "Individual feature");
tf.app.flags.DEFINE_integer("frames", "5", "How many frames to run");
tf.app.flags.DEFINE_integer("octaves", "5", "How many mage octaves (scales)");
tf.app.flags.DEFINE_integer("iterations", "10", "How many gradient iterations per octave");
tf.app.flags.DEFINE_float("octave_scale", "1.4", "Octave scaling factor");
tf.app.flags.DEFINE_float("frame_scale", "1.0", "Frame scaling factor");
tf.app.flags.DEFINE_boolean("frame_crop", "false", "Frame crop to original");
tf.app.flags.DEFINE_integer("tilesize", "256", "Size of tiles. Decrease if out of GPU memory. Increase if bad utilization.");

FLAGS = tf.app.flags.FLAGS

# creating TensorFlow session and loading the model
graph = tf.Graph()
sess = tf.InteractiveSession(graph=graph, config=tf.ConfigProto(log_device_placement=False))
graph_def = tf.GraphDef()
with open(FLAGS.model, 'rb') as g:
    model = g.read()
    graph_def.ParseFromString(model)
t_input = tf.placeholder(np.float32, name='input') # define the input tensor
imagenet_mean = 117.0
t_preprocessed = tf.expand_dims(t_input-imagenet_mean, 0)
tf.import_graph_def(graph_def, {'input':t_preprocessed})

print("--- Available Layers: ---")
layers = []
for name in (op.name for op in graph.get_operations()):
  layer_shape = graph.get_tensor_by_name(name+':0').get_shape()
  if not layer_shape.ndims: continue
  layers.append((name, int(layer_shape[-1])))
  print(name, "Features/Channels: ", int(layer_shape[-1]))
print('Number of layers', len(layers))
print('Total number of feature channels:', sum((layer[1] for layer in layers)))
print('Chosen layer: ')
print(graph.get_operation_by_name(FLAGS.layer))

def T(layer):
    '''Helper for getting layer output tensor'''
    return graph.get_tensor_by_name("%s:0"%layer)

def tffunc(*argtypes):
    '''Helper that transforms TF-graph generating function into a regular one.
    See "resize" function below.
    '''
    placeholders = list(map(tf.placeholder, argtypes))  # Need a list here, while P3 returns a map object!
    print(placeholders, type(placeholders))
    def wrap(f):
        out = f(*placeholders)
        def wrapper(*args, **kw):
            return out.eval(dict(zip(placeholders, args)), session=kw.get('session'))
        return wrapper
    return wrap

# Helper function that uses TF to resize an image
def resize(img, size):
    img = tf.expand_dims(img, 0)
    return tf.image.resize_bilinear(img, size)[0,:,:,:]
resize = tffunc(np.float32, np.int32)(resize)

def calc_grad_tiled(img, t_grad, tile_size=512):
    '''Compute the value of tensor t_grad over the image in a tiled way.
    Random shifts are applied to the image to blur tile boundaries over
    multiple iterations.'''
    sz = tile_size
    h, w = img.shape[:2]
    sx, sy = np.random.randint(sz, size=2)
    img_shift = np.roll(np.roll(img, sx, 1), sy, 0)
    grad = np.zeros_like(img)
    for y in range(0, max(h-sz//2, sz),sz):
        for x in range(0, max(w-sz//2, sz),sz):
            sub = img_shift[y:y+sz,x:x+sz]
            g = sess.run(t_grad, {t_input:sub})
            grad[y:y+sz,x:x+sz] = g
    return np.roll(np.roll(grad, -sx, 1), -sy, 0)

def render_deepdream(t_obj, img,
                     iter_n=10, step=1.5, octave_n=12, octave_scale=1.4):
    t_score = tf.reduce_mean(t_obj)
    t_grad = tf.gradients(t_score, t_input)[0]

    # split the image into a number of octaves
    img = img
    octaves = []
    for i in range(octave_n-1):
        hw = img.shape[:2]
        lo = resize(img, np.int32(np.float32(hw)/octave_scale))
        hi = img-resize(lo, hw)
        img = lo
        octaves.append(hi)

    # generate details octave by octave
    for octave in range(octave_n):
        print(" Octave: ", octave, "Res: ", img.shape)
        if octave>0:
            hi = octaves[-octave]
            img = resize(img, hi.shape[:2])+hi
        for i in range(iter_n):
            g = calc_grad_tiled(img, t_grad, FLAGS.tilesize)
            img += g*(step / (np.abs(g).mean()+1e-7))
    return img

def main(_):
  if FLAGS.input:
    img = np.float32(PIL.Image.open(FLAGS.input));
  else:
    img = np.float32(np.full((1024,1024,3), 128))

  start_shape = img.shape

  # Make RGB if greyscale:
  if len(img.shape)==2 or img.shape[2] == 1:
    img = np.stack([img]*3, axis=2)

  for i_frame in range(FLAGS.frames):
    if FLAGS.frame_scale > 1.0:
      img = resize(img, np.int32(np.float32(img.shape[:2])*FLAGS.frame_scale))
    if FLAGS.frame_crop:
      img = img[img.shape[0]//2-start_shape[0]//2 : img.shape[0]//2-start_shape[0]//2 + start_shape[0],
                img.shape[1]//2-start_shape[1]//2 : img.shape[1]//2-start_shape[1]//2 + start_shape[1],:]

    print("Cycle", i_frame, " Res:", img.shape)
    t_obj = tf.square(T(FLAGS.layer))
    if FLAGS.feature >= 0:
      t_obj = T(FLAGS.layer)[:,:,:,FLAGS.feature]
    img = render_deepdream(t_obj, img,
        iter_n = FLAGS.iterations,
        octave_n = FLAGS.octaves,
        octave_scale = FLAGS.octave_scale)
    print("Saving ", i_frame)
    img = np.uint8(np.clip(img, 0, 255))
    PIL.Image.fromarray(img).save("%s_%05d.jpg"%(FLAGS.output, i_frame), "jpeg", quality=98)

if __name__ == "__main__":
  tf.app.run()
