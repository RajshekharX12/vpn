import qrcode

def create_qr(config):

    img = qrcode.make(config)
    path = "config_qr.png"
    img.save(path)

    return path
