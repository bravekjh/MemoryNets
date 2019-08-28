import argparse
from RNN import RNN

def str2bool(v):
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')


def select_network(net_type, inp_size, hid_size, nonlin, rinit, iinit, cuda):
    if net_type == 'RNN':
        rnn = RNN(inp_size, hid_size, nonlin, bias=True, cuda=cuda, r_initializer=rinit, i_initializer=iinit)
    return rnn