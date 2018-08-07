
import subprocess as _subprocess
import sys

def _patch_py3_subprocess(subprocess):
    if sys.version_info.major >= 3:
        from codecs import utf_8_decode, utf_8_encode
        from subprocess import check_output, Popen

        def _check_output(*args, **kwargs):
            out = check_output(*args, **kwargs)
            if isinstance(out, bytes):
                out = utf_8_decode(out)[0]
            return out

        class _Popen(Popen):

            def __init__(self, *args, **kwargs):
                super(_Popen, self).__init__(*args, **kwargs)

            def communicate(self, input=None, timeout=None):
                if isinstance(input, str):
                    input = utf_8_encode(input)[0]
                out, err = super(_Popen, self).communicate(input=input,
                                                           timeout=timeout)
                if isinstance(out, bytes):
                    out = utf_8_decode(out)[0]
                if isinstance(err, bytes):
                    err = utf_8_decode(err)[0]
                return out, err


        if isinstance(check_output(['/bin/echo', 'abc']), bytes):
            subprocess.check_output = _check_output
            subprocess.Popen = _Popen
    return subprocess

subprocess = _patch_py3_subprocess(_subprocess)

