# Dynamic memory networks in Theano
The aim of this repository is to implement Dynamic memory networks 
as described in the [paper by Kumar et al.](http://arxiv.org/abs/1506.07285)
and to experiment with its various extensions.

**Pretrained models on bAbI tasks can be tested [online](http://yerevann.com/dmn-ui/).**

We will cover the process in a series of blog posts.
* [The first post](http://yerevann.github.io/2016/02/05/implementing-dynamic-memory-networks/) describes the details of the basic architecture and presents our first results on [bAbI tasks](http://fb.ai/babi) v1.2.
* [The second post](http://yerevann.github.io/2016/02/23/playground-for-babi-tasks/) describes our second model called `dmn_smooth` and introduces our [playground for bAbI tasks](http://yerevann.com/dmn-ui/).

## Repository contents

| file | description |
| --- | --- |
| `main.py` | the main entry point to train and test available network architectures on bAbI-like tasks |
| `dmn_basic.py` | our baseline implementation. It is as close to the original as we could understand the paper, except the number of steps in the main memory GRU is fixed. Attention module uses `T.abs_` function as a distance between two vectors which causes gradients to become `NaN` randomly.  The results reported in [this blog post](http://yerevann.github.io/2016/02/05/implementing-dynamic-memory-networks/) are based on this network |
| `dmn_smooth.py` | uses the square of the Euclidean distance instead of `abs` in the attention module. Training is very stable. Performance on bAbI is slightly better |
| `dmn_batch.py` | `dmn_smooth` with minibatch training support. The batch size cannot be set to `1` because of the [Theano bug](https://github.com/Theano/Theano/issues/1772) | 
| `dmn_qa_draft.py` | draft version of a DMN designed for answering multiple choice questions | 
| `utils.py` | tools for working with bAbI tasks and GloVe vectors |
| `nn_utils.py` | helper functions on top of Theano and Lasagne |
| `fetch_babi_data.sh` | shell script to fetch bAbI tasks (adapted from [MemN2N](https://github.com/npow/MemN2N)) |
| `fetch_glove_data.sh` | shell script to fetch GloVe vectors (by [5vision](https://github.com/5vision/kaggle_allen)) |
| `server/` | contains Flask-based restful api server |


## Usage

This implementation is based on Theano and Lasagne. One way to install them is:

    pip install -r https://raw.githubusercontent.com/Lasagne/Lasagne/master/requirements.txt
    pip install https://github.com/Lasagne/Lasagne/archive/master.zip

The following bash scripts will download bAbI tasks and GloVe vectors.

    ./fetch_babi_data.sh
    ./fetch_glove_data.sh

Use `main.py` to train a network:

    python main.py --network dmn_basic --babi_id 1

The states of the network will be saved in `states/` folder. 
There is one pretrained state on the 1st bAbI task. It should give 100% accuracy on the test set:

    python main.py --network dmn_basic --mode test --babi_id 1 --load_state states/dmn_basic.mh5.n40.babi1.epoch4.test0.00033.state

## MCTest data preprocessing:
download MCTest data into data/MCTest.
in root folder, run
    
    python mctest_parse.py [mc160|mc500] [50|100|200|300]
    
this generates the embedding matrix for mc160 and mc500, from glove.[50] ect.

the parser also have a function called by main_mc to generate a parsed dataset (converted to index). The returned data structure is a list of {"C":[[w]],"Q":[w],"A":[w],"O":[[w]]} for each question task

## MCTest run
run the main mctest network training
    
    python main_mc.py --network mc_gru_dot_fix --id mc160

see the main_mc function for a list of options

## Visualize episode memory
view_babi and view_mc can visualize attention gate over episode. Need to load from pretrain model. Currently only dmn_smooth, dmn_batch, mc_gru_dot_fix network supports viewing.

    python view_babi.py --network dmn_smooth --babi_id 2 --load_state states/dmn_smooth.mh3.n40.bs10.babi2.epoch29.test6.43988.state
    
    python view_mc.py --network mc_gru_dot_fix --id mc160 --load_state states/gru_dot_fix.mh3.n40.bs10.d0.3.mc160.epoch25.test5.22941.state
    
## Roadmap

* Mini-batch training ([done](https://github.com/YerevaNN/Dynamic-memory-networks-in-Theano/blob/master/dmn_batch.py), 08/02/2016)
* Web interface ([done](https://github.com/YerevaNN/dmn-ui), 08/23/2016)
* Visualization of episodic memory module ([done](https://github.com/YerevaNN/dmn-ui), 08/23/2016)
* Regularization (work in progress, L2 doesn't help at all, dropout and batch normalization help a little)
* Support for multiple-choice questions ([work in progress](https://github.com/YerevaNN/Dynamic-memory-networks-in-Theano/blob/master/dmn_qa_draft.py))
* Evaluation on more complex datasets
* Import some ideas from [Neural Reasoner](http://arxiv.org/abs/1508.05508)
