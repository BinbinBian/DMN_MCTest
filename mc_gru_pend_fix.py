import numpy as np

import theano
import theano.tensor as T
from theano.compile.nanguardmode import NanGuardMode

import lasagne
from lasagne import layers
from lasagne import nonlinearities
import cPickle as pickle

import utils
import nn_utils
import mc_utils

floatX = theano.config.floatX

class DMN:
    
    def __init__(self, train_raw, dev_raw, test_raw, word2vec, word_vector_size, 
                dim, mode, input_mask_mode, memory_hops, l2, lr, normalize_attention, dropout, **kwargs):
        print "==> model: GRU, pending options, fixed embedding"
        print "==> not used params in DMN class:", kwargs.keys()
        self.word2vec = word2vec      
        self.word_vector_size = word_vector_size
        self.dim = dim
        self.mode = mode
        self.input_mask_mode = input_mask_mode
        self.memory_hops = memory_hops
        #self.batch_size = 1
        self.l2 = l2
        self.lr = lr
        self.normalize_attention = normalize_attention
        self.dropout = dropout
        
        self.train_input, self.train_q, self.train_answer, self.train_choices, self.train_input_mask = self._process_input(train_raw)
        self.dev_input, self.dev_q, self.dev_answer, self.dev_choices, self.dev_input_mask = self._process_input(dev_raw)
        self.test_input, self.test_q, self.test_answer, self.test_choices, self.test_input_mask = self._process_input(test_raw)
        self.vocab_size = 4 # number of answer choices
        
        self.inp_var = T.matrix('input_var')
        self.q_var = T.matrix('question_var')
        self.ca_var = T.matrix('ca_var')
        self.cb_var = T.matrix('cb_var')
        self.cc_var = T.matrix('cc_var')
        self.cd_var = T.matrix('cd_var')
        self.ans_var = T.iscalar('answer_var')
        self.input_mask_var = T.ivector('input_mask_var')
        
        print "==> building input module"
        self.W_inp_res_in = theano.shared(lasagne.init.Normal(0.1).sample((self.dim, self.word_vector_size)), borrow=True)
        self.W_inp_res_hid = theano.shared(lasagne.init.Normal(0.1).sample((self.dim, self.dim)), borrow=True)
        self.b_inp_res = theano.shared(lasagne.init.Constant(0.0).sample((self.dim,)), borrow=True)
        
        self.W_inp_upd_in = theano.shared(lasagne.init.Normal(0.1).sample((self.dim, self.word_vector_size)), borrow=True)
        self.W_inp_upd_hid = theano.shared(lasagne.init.Normal(0.1).sample((self.dim, self.dim)), borrow=True)
        self.b_inp_upd = theano.shared(lasagne.init.Constant(0.0).sample((self.dim,)), borrow=True)
        
        self.W_inp_hid_in = theano.shared(lasagne.init.Normal(0.1).sample((self.dim, self.word_vector_size)), borrow=True)
        self.W_inp_hid_hid = theano.shared(lasagne.init.Normal(0.1).sample((self.dim, self.dim)), borrow=True)
        self.b_inp_hid = theano.shared(lasagne.init.Constant(0.0).sample((self.dim,)), borrow=True)
        
        inp_c_history, _ = theano.scan(fn=self.input_gru_step, 
                    sequences=self.inp_var,
                    outputs_info=T.zeros_like(self.b_inp_hid))
        
        self.inp_c = inp_c_history.take(self.input_mask_var, axis=0)
        
        self.q_q, _ = theano.scan(fn=self.input_gru_step, 
                    sequences=self.q_var,
                    outputs_info=T.zeros_like(self.b_inp_hid))

        self.q_q = self.q_q[-1]
        
        self.c_vecs = []
        for choice in [self.ca_var, self.cb_var, self.cc_var, self.cd_var]:
            history, _ = theano.scan(fn=self.input_gru_step, 
                    sequences=choice,
                    outputs_info=T.zeros_like(self.b_inp_hid))
            self.c_vecs.append(history[-1])
        
        
        self.c_vecs = T.stack(self.c_vecs).transpose((1, 0)) # (dim, 4)
        self.inp_c = T.stack([self.inp_c] * 4).transpose((1, 2, 0)) # (fact_cnt, dim, 4)
        self.q_q = T.stack([self.q_q] * 4).transpose((1, 0)) # (dim, 4)
        
        
        print "==> creating parameters for memory module"
        self.W_mem_res_in = theano.shared(lasagne.init.Normal(0.1).sample((self.dim, self.dim)), borrow=True)
        self.W_mem_res_hid = theano.shared(lasagne.init.Normal(0.1).sample((self.dim, self.dim)), borrow=True)
        self.b_mem_res = theano.shared(lasagne.init.Constant(0.0).sample((self.dim,)), borrow=True)
        
        self.W_mem_upd_in = theano.shared(lasagne.init.Normal(0.1).sample((self.dim, self.dim)), borrow=True)
        self.W_mem_upd_hid = theano.shared(lasagne.init.Normal(0.1).sample((self.dim, self.dim)), borrow=True)
        self.b_mem_upd = theano.shared(lasagne.init.Constant(0.0).sample((self.dim,)), borrow=True)
        
        self.W_mem_hid_in = theano.shared(lasagne.init.Normal(0.1).sample((self.dim, self.dim)), borrow=True)
        self.W_mem_hid_hid = theano.shared(lasagne.init.Normal(0.1).sample((self.dim, self.dim)), borrow=True)
        self.b_mem_hid = theano.shared(lasagne.init.Constant(0.0).sample((self.dim,)), borrow=True)
        
        self.W_b = theano.shared(lasagne.init.Normal(0.1).sample((self.dim, self.dim)), borrow=True)
        self.W_1 = theano.shared(lasagne.init.Normal(0.1).sample((self.dim, 10 * self.dim + 3)), borrow=True)
        self.W_2 = theano.shared(lasagne.init.Normal(0.1).sample((1, self.dim)), borrow=True)
        self.b_1 = theano.shared(lasagne.init.Constant(0.0).sample((self.dim,)), borrow=True)
        self.b_2 = theano.shared(lasagne.init.Constant(0.0).sample((1,)), borrow=True)
        

        print "==> building episodic memory module (fixed number of steps: %d)" % self.memory_hops
        memory = [self.q_q.copy()] # (dim, 4)
        for iter in range(1, self.memory_hops + 1):
            current_episode = self.new_episode(memory[iter - 1])
            memory.append(self.GRU_update_batch(memory[iter - 1], current_episode,
                                          self.W_mem_res_in, self.W_mem_res_hid, self.b_mem_res, 
                                          self.W_mem_upd_in, self.W_mem_upd_hid, self.b_mem_upd,
                                          self.W_mem_hid_in, self.W_mem_hid_hid, self.b_mem_hid))
                                      
        last_mem_raw = memory[-1].flatten().dimshuffle('x', 0) # (dim*4)
        net = layers.InputLayer(shape=(1, 4 * self.dim), input_var=last_mem_raw)
        if self.dropout > 0 and self.mode == 'train':
            net = layers.DropoutLayer(net, p=self.dropout)
        last_mem = layers.get_output(net)[0]

        print "==> building answer module"
        self.W_a = theano.shared(lasagne.init.Normal(0.1).sample((self.vocab_size, 4 * self.dim)), borrow=True)
        self.prediction = nn_utils.softmax(T.dot(self.W_a, last_mem))
        
        
        print "==> collecting all parameters" # embedding matrix is not trained
        self.params = [self.W_inp_res_in, self.W_inp_res_hid, self.b_inp_res, 
                  self.W_inp_upd_in, self.W_inp_upd_hid, self.b_inp_upd,
                  self.W_inp_hid_in, self.W_inp_hid_hid, self.b_inp_hid,
                  self.W_mem_res_in, self.W_mem_res_hid, self.b_mem_res, 
                  self.W_mem_upd_in, self.W_mem_upd_hid, self.b_mem_upd,
                  self.W_mem_hid_in, self.W_mem_hid_hid, self.b_mem_hid,
                  self.W_b, self.W_1, self.W_2, self.b_1, self.b_2, self.W_a]
        
        
        print "==> building loss layer and computing updates"
        self.loss_ce = T.nnet.categorical_crossentropy(self.prediction.dimshuffle('x', 0), T.stack([self.ans_var]))[0]
        if self.l2 > 0:
            self.loss_l2 = self.l2 * nn_utils.l2_reg(self.params)
        else:
            self.loss_l2 = 0
        
        self.loss = self.loss_ce + self.loss_l2
        
        updates = lasagne.updates.adadelta(self.loss, self.params, learning_rate=self.lr)
        
        if self.mode == 'train':
            print "==> compiling train_fn"
            self.train_fn = theano.function(inputs=[self.inp_var, self.q_var, self.ans_var,
                                                    self.ca_var, self.cb_var, self.cc_var, self.cd_var,
                                                    self.input_mask_var],
                                            allow_input_downcast = True,
                                            outputs=[self.prediction, self.loss],
                                            updates=updates)
        
        print "==> compiling test_fn"
        self.test_fn = theano.function(inputs=[self.inp_var, self.q_var, self.ans_var,
                                               self.ca_var, self.cb_var, self.cc_var, self.cd_var,
                                               self.input_mask_var],
                                       allow_input_downcast = True,
                                       outputs=[self.prediction, self.loss, self.inp_c, self.q_q, last_mem])
        
        
        if self.mode == 'train':
            print "==> computing gradients (for debugging)"
            gradient = T.grad(self.loss, self.params)
            self.get_gradient_fn = theano.function(inputs=[self.inp_var, self.q_var, self.ans_var,
                                                           self.ca_var, self.cb_var, self.cc_var, self.cd_var,
                                                           self.input_mask_var],
                                                   allow_input_downcast = True,
                                                   outputs=gradient)
    
    
    def GRU_update(self, h, x, W_res_in, W_res_hid, b_res,
                         W_upd_in, W_upd_hid, b_upd,
                         W_hid_in, W_hid_hid, b_hid):
        """ mapping of our variables to symbols in DMN paper: 
        W_res_in = W^r
        W_res_hid = U^r
        b_res = b^r
        W_upd_in = W^z
        W_upd_hid = U^z
        b_upd = b^z
        W_hid_in = W
        W_hid_hid = U
        b_hid = b^h
        """
        z = T.nnet.sigmoid(T.dot(W_upd_in, x) + T.dot(W_upd_hid, h) + b_upd)
        r = T.nnet.sigmoid(T.dot(W_res_in, x) + T.dot(W_res_hid, h) + b_res)
        _h = T.tanh(T.dot(W_hid_in, x) + r * T.dot(W_hid_hid, h) + b_hid)
        return z * h + (1 - z) * _h
    
    
    def GRU_update_batch(self, h, x, W_res_in, W_res_hid, b_res,
                         W_upd_in, W_upd_hid, b_upd,
                         W_hid_in, W_hid_hid, b_hid):
        """ mapping of our variables to symbols in DMN paper: 
        W_res_in = W^r
        W_res_hid = U^r
        b_res = b^r
        W_upd_in = W^z
        W_upd_hid = U^z
        b_upd = b^z
        W_hid_in = W
        W_hid_hid = U
        b_hid = b^h
        """
        z = T.nnet.sigmoid(T.dot(W_upd_in, x) + T.dot(W_upd_hid, h) + b_upd.dimshuffle(0, 'x'))
        r = T.nnet.sigmoid(T.dot(W_res_in, x) + T.dot(W_res_hid, h) + b_res.dimshuffle(0, 'x'))
        _h = T.tanh(T.dot(W_hid_in, x) + r * T.dot(W_hid_hid, h) + b_hid.dimshuffle(0, 'x'))
        return z * h + (1 - z) * _h
    
    
    def input_gru_step(self, x, prev_h):
        return self.GRU_update(prev_h, x, self.W_inp_res_in, self.W_inp_res_hid, self.b_inp_res, 
                                     self.W_inp_upd_in, self.W_inp_upd_hid, self.b_inp_upd,
                                     self.W_inp_hid_in, self.W_inp_hid_hid, self.b_inp_hid)
    
    
    def new_attention_step(self, ct, prev_g, mem, q_q, c_vecs):
        cWq = T.dot(T.ones((1, 4), dtype=floatX), T.dot(T.dot(ct.T, self.W_b), q_q) * T.eye(n=4, m=4, dtype=floatX))
        cWm = T.dot(T.ones((1, 4), dtype=floatX), T.dot(T.dot(ct.T, self.W_b), mem) * T.eye(n=4, m=4, dtype=floatX))
        cWc_vecs = T.dot(T.ones((1, 4), dtype=floatX), T.dot(T.dot(ct.T, self.W_b), c_vecs) * T.eye(n=4, m=4, dtype=floatX))
        
        z = T.concatenate([ct, mem, q_q, c_vecs, ct * q_q, ct * mem, ct * c_vecs, 
                           ct - q_q, ct - mem, ct - c_vecs, 
                           cWq, cWm, cWc_vecs], axis=0)
        
        l_1 = T.dot(self.W_1, z) + self.b_1.dimshuffle(0, 'x')
        l_1 = T.tanh(l_1)
        l_2 = T.dot(self.W_2, l_1) + self.b_2.dimshuffle(0, 'x')
        G = T.nnet.sigmoid(l_2)[0]
        return G
        
        
    def new_episode_step(self, ct, g, prev_h):
        gru = self.GRU_update_batch(prev_h, ct,
                             self.W_mem_res_in, self.W_mem_res_hid, self.b_mem_res, 
                             self.W_mem_upd_in, self.W_mem_upd_hid, self.b_mem_upd,
                             self.W_mem_hid_in, self.W_mem_hid_hid, self.b_mem_hid)
        
        h = g * gru + (1 - g) * prev_h
        return h
       
    
    def new_episode(self, mem):
        g, g_updates = theano.scan(fn=self.new_attention_step,
            sequences=self.inp_c,
            non_sequences=[mem, self.q_q, self.c_vecs],
            outputs_info=T.zeros_like(self.inp_c[0][0])) 
        
        if (self.normalize_attention):
            g = nn_utils.softmax(g)
        
        e, e_updates = theano.scan(fn=self.new_episode_step,
            sequences=[self.inp_c, g],
            outputs_info=T.zeros_like(self.inp_c[0]))
        
        return e[-1]

    
    def save_params(self, file_name, epoch, **kwargs):
        with open(file_name, 'w') as save_file:
            pickle.dump(
                obj = {
                    'params' : [x.get_value() for x in self.params],
                    'epoch' : epoch, 
                    'gradient_value': (kwargs['gradient_value'] if 'gradient_value' in kwargs else 0)
                },
                file = save_file,
                protocol = -1
            )
    
    def load_gate(self, file_name):
        print "==> loading gate weights from %s" % file_name
        with open(file_name, 'r') as load_file:
            dict = pickle.load(load_file)
            loaded_params = dict['params']
            self.W_b.set_value(dict['W_b'])
            self.W_1.set_value(dict['W_1'])
            self.W_2.set_value(dict['W_2'])
            self.b_1.set_value(dict['b_1'])
            self.b_2.set_value(dict['b_2'])
            
            
    def load_state(self, file_name):
        print "==> loading state %s" % file_name
        with open(file_name, 'r') as load_file:
            dict = pickle.load(load_file)
            loaded_params = dict['params']
            for (x, y) in zip(self.params, loaded_params):
                x.set_value(y)


    def _find_first(self, lst, val):
        for (i, x) in enumerate(lst):
            if (x == val):
                return i
        return -1
        
    def _process_input(self, data_raw):
        return mc_utils.process_input_glove(data_raw, self.word2vec, self.input_mask_mode)
        
    
    def get_batches_per_epoch(self, mode):
        if (mode == 'train'):
            return len(self.train_input)
        elif (mode == 'dev'):
            return len(self.dev_input)
        elif (mode == 'test'):
            return len(self.test_input)
        raise Exception("unknown mode")
    
    
    def step(self, batch_index, mode):
        if mode == "train" and self.mode == "test":
            raise Exception("Cannot train during test mode")
        
        if mode == "train":
            theano_fn = self.train_fn 
            inputs = self.train_input
            qs = self.train_q
            answers = self.train_answer
            choices = self.train_choices
            input_masks = self.train_input_mask
        elif mode == "test":    
            theano_fn = self.test_fn 
            inputs = self.test_input
            qs = self.test_q
            answers = self.test_answer
            choices = self.test_choices
            input_masks = self.test_input_mask
        elif mode == "dev":    
            theano_fn = self.test_fn 
            inputs = self.dev_input
            qs = self.dev_q
            answers = self.dev_answer
            choices = self.dev_choices
            input_masks = self.dev_input_mask
        else:
            raise Exception("Invalid mode")
            
        inp = inputs[batch_index]
        q = qs[batch_index]
        ans = answers[batch_index]
        ca = choices[batch_index][0]
        cb = choices[batch_index][1]
        cc = choices[batch_index][2]
        cd = choices[batch_index][3]
        input_mask = input_masks[batch_index]

        skipped = 0
        grad_norm = float('NaN')
        
        if mode == 'train':
            gradient_value = self.get_gradient_fn(inp, q, ans, ca, cb, cc, cd, input_mask)
            grad_norm = np.max([utils.get_norm(x) for x in gradient_value])
            
            if (np.isnan(grad_norm)):
                print "==> gradient is nan at index %d." % batch_index
                print "==> skipping"
                skipped = 1
        
        if skipped == 0:
            ret = theano_fn(inp, q, ans, ca, cb, cc, cd, input_mask)
        else:
            ret = [float('NaN'), float('NaN')]
        
        param_norm = np.max([utils.get_norm(x.get_value()) for x in self.params])
        
        return {"prediction": np.array([ret[0]]),
                "answers": np.array([ans]),
                "current_loss": ret[1],
                "skipped": skipped,
                "log": "pn: %.3f \t gn: %.3f" % (param_norm, grad_norm)
                }
