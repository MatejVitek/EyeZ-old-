from abc import ABC, abstractmethod
import numpy as np
import scipy as sp

from keras.layers import Dense, Flatten
from keras.models import Sequential
from keras.optimizers import SGD, RMSprop

from evaluation import Evaluation
from image_generators import ImageGenerator, LabeledImageGenerator


class CVModel(ABC):
	@abstractmethod
	def evaluate(self, gallery, probe, evaluation=None):
		pass


class NNModel(CVModel):
	def __init__(self, model, **kw):
		"""
		NN model wrapper for cross-validation

		:param model: Model to evaluate (should not include the softmax layer)
		:param int batch_size: Batch size
		:param distance: Distance metric for evaluation (passed to scipy.spacial.distance.cdist)
		"""

		# Base model settings
		self.model = model
		self.input_size = self.model.input_shape[1:3]
		if any(size is None for size in self.input_size):
			self.input_size = (256, 256)

		# Other settings
		self.batch_size = kw.get('batch_size', 32)
		self.dist = kw.get('distance') or kw.get('dist', 'cosine')

		self.verbose = 0

	def evaluate(self, gallery, probe, evaluation=None, plot=None, verbose=1):
		"""
		Evaluate wrapped model

		:param iterable gallery: List of gallery samples
		:param iterable probe: List of probe samples
		:param evaluation: Existing Evaluation to update. If None, new Evaluation will be created.
		:type  evaluation: Evaluation or None
		:param plot: Plotting function, taking a tuple (x, y, xlabel, ylabel, figure). If None, will not plot.
		:type  plot: Callable or None
		:param int verbose: Verbosity level. If nonzero, will print output. Also passed to underlying keras methods.

		:return: Evaluation updated with newly computed metrics
		:rtype:  Evaluation
		"""

		self.verbose = verbose
		if not evaluation:
			evaluation = Evaluation()
		g_gen = ImageGenerator(
			gallery,
			target_size=self.input_size,
			batch_size=self.batch_size,
			shuffle=False
		)
		p_gen = ImageGenerator(
			probe,
			target_size=self.input_size,
			batch_size=self.batch_size,
			shuffle=False
		)

		# rows = samples, columns = features
		self._print("Predicting gallery features:")
		g_features = self.model.predict_generator(g_gen, verbose=self.verbose)
		self._print("Predicting probe features:")
		p_features = self.model.predict_generator(p_gen, verbose=self.verbose)

		g_classes = [s.label for s in gallery]
		p_classes = [s.label for s in probe]

		# rows = gallery, columns = probe
		dist_matrix = np.absolute(sp.spatial.distance.cdist(g_features, p_features, metric=self.dist))

		# Get FAR and FRR
		far, frr, threshold = evaluation.compute_error_rates(dist_matrix, g_classes, p_classes, n_points=5000)

		# EER
		eer = evaluation.update_eer()
		self._print(f"EER: {eer}")
		if plot:
			plot(threshold, far, "Threshold", "FAR", figure="EER")
			plot(threshold, frr, "Threshold", "FRR", figure="EER")

		# AUC
		auc = evaluation.update_auc()
		self._print(f"AUC: {auc}")
		if plot:
			plot(far, 1 - frr, "FAR", "TAR", figure="ROC Curve")

		ver1far = evaluation.update_ver1far()
		self._print(f"VER@1FAR: {ver1far}")

		return evaluation

	def _print(self, s):
		if self.verbose:
			print(s)


class TrainableNNModel(NNModel):
	def __init__(self, model, **kw):
		"""
		Wrapper for a trainable model for CV

		:param int primary_epochs: Epochs to train top layers only
		:param int secondary_epochs: Epochs to train unfrozen layers and top layers
		:param int feature_size: Feature size of custom (FC) feature layer. If 0, no custom feature layer will be added.
		:param first_unfreeze: Index of the first layer to unfreeze in secondary training. If None, skip primary training and train the whole model.
		:type  first_unfreeze: int or None
		:param primary_opt: Optimizer to use in primary training
		:param secondary_opt: Optimizer to use in secondary training
		"""

		super().__init__(model, **kw)
		self.epochs1 = kw.get('primary_epochs') or kw.get('top_epochs') or kw.get('epochs1') or kw.get('epochs', 50)
		self.epochs2 = kw.get('secondary_epochs') or kw.get('unfrozen_epochs') or kw.get('epochs2', 30)
		self.feature_size = kw.get('feature_size', 1024)
		self.first_unfreeze = kw.get('first_unfreeze')
		self.opt1 = kw.get('primary_opt') or kw.get('opt1') or kw.get('opt', 'rmsprop')
		self.opt2 = kw.get('secondary_opt') or kw.get('opt2', SGD(lr=0.0001, momentum=0.9))

		self.base = self.model
		self.base_weights = self.base.get_weights()

		self.model = None
		self.n_classes = None

	def train(self, train_data, validation_data):
		"""
		Train wrapped model on data

		:param train_data: Training data
		:param validation_data: Validation data
		"""

		self._count_classes(train_data + validation_data)
		self._build_model()
		self._train_model(train_data, validation_data)
		self.model.pop()

	def reset(self):
		"""
		Reset model to pre-training state
		"""

		for layer in self.base.layers:
			layer.trainable = True
		self.base.set_weights(self.base_weights)
		self.model = None

	def _count_classes(self, data):
		self.n_classes = len({s.label for s in data})

	def _build_model(self):
		# Add own top layer(s)
		self.model = Sequential()
		self.model.add(self.base)
		if self.feature_size:
			self.model.add(Dense(
				self.feature_size,
				name='top_fc',
				activation='relu'
			))
		self.model.add(Dense(
			self.n_classes,
			name='top_softmax',
			activation='softmax'
		))

	def _train_model(self, t_data, v_data):
		t_gen = LabeledImageGenerator(
			t_data,
			self.n_classes,
			target_size=self.input_size,
			batch_size=self.batch_size
		)
		v_gen = LabeledImageGenerator(
			v_data,
			self.n_classes,
			target_size=self.input_size,
			batch_size=self.batch_size
		)

		if self.first_unfreeze is not None:
			# Freeze base layers
			for layer in self.base.layers:
				layer.trainable = False
			print("Training top layers:")
			self._fit_model(t_gen, v_gen, epochs=self.epochs1, opt=self.opt1, loss='categorical_crossentropy')

			# Unfreeze the last few base layers
			for layer in self.base.layers[self.first_unfreeze:]:
				layer.trainable = True
			print("Training unfrozen layers:")
			self._fit_model(t_gen, v_gen, epochs=self.epochs2, opt=self.opt2, loss='categorical_crossentropy')

		else:
			print("Training model:")
			self._fit_model(t_gen, v_gen, epochs=self.epochs1, opt=self.opt1, loss='categorical_crossentropy')

	def _fit_model(self, t_gen, v_gen, epochs, opt='SGD', loss='categorical_crossentropy'):
		self.model.compile(optimizer=opt, loss=loss, metrics=['accuracy'])
		self.model.fit_generator(
			t_gen,
			epochs=epochs,
			validation_data=v_gen
		)
