


import multer from 'multer'
import path from 'path'
import fs from 'fs/promises'
import logger from '../utils/logger.js'
import { errorResponse } from '../utils/apiResponse.js'

const TEMP_DIR = path.join(__dirname,'../../temp');




const ALLOWED_MIME_TYPES = [
  'audio/mpeg',
  'audio/wav',
  'audio/wave',
  'audio/x-wav',
  'audio/mp4',
  'audio/x-m4a',
  'audio/ogg',
  'audio/webm',
  'video/webm',
]


const ALLOWED_EXTENSIONS = ['.mp3', '.wav', '.m4a', '.ogg', '.webm']


const MAX_FILE_SIZE = 100 * 1024 * 1024

export const ensuresTempDir = async () => {
  if(!fs.existsSync(TEMP_DIR)) {
    fs.mkdirSync(TEMP_DIR,{recursive: true})
  }
}




//Storage - disk storage in temp folder
//files are upload to cloudinary immediatly
//after multer saves them then delete from disk

const storage = multer.diskStorage({
  destination: async (req, file, cb) => {
    await ensureTempDir();
    cb(null, TEMP_DIR);
  },
  filename: (req, file, cb) => {
    const ext = path.extname(file.originalname) || '.webm';
    const uniqueName = `audio-${req.params.id}-${Date.now()}${ext}`;
    cb(null, uniqueName);
  },
});


//File filter

const fileFilter = (req, file, cb) => {
  const ext = path.extname(file.originalname).toLowerCase();
  const mimeOk = ALLOWED_MIME_TYPES.includes(file.mimetype);
  const extOk = ALLOWED_EXTENSIONS.includes(ext);

  if (mimeOk || extOk) {
    cb(null, true);
  } else {
    cb(new Error(`Unsupported audio format: ${file.mimetype} (${ext})`));
  }
};

//multer instance

const upload = multer({
    storage,
    limits: {
        fileSize: MAX_FILE_SIZE,
        files: 1
    },
    fileFilter
})


//After this middleware runs, audio file is at req.file
//req.file = {fieldname,originalname,mimetype,size,path,filename}

export const uploadAudioMiddleware = (req,res,next) => {
    const multerSingle = upload.single('audio')

    multerSingle(req,res,(err) => {
        if(err instanceof multer.MulterError) {
             if (err.code === 'LIMIT_FILE_SIZE') {
        return errorResponse(
          res,
          `File too large. Maximum size is ${MAX_FILE_SIZE / (1024 * 1024)}MB.`,
          413
        )
      }
      if (err.code === 'LIMIT_UNEXPECTED_FILE') {
        return errorResponse(
          res,
          'Unexpected file field. Use field name "audio".',
          400
        )
      }
      return errorResponse(res, `Upload error: ${err.message}`, 400)
    }
        if (err) {
      return errorResponse(res, err.message, 400)
    }

    // No file uploaded — some routes allow optional audio
    if (!req.file) {
      logger.warn('No audio file in request', { url: req.originalUrl })
    }

    next()
  })
}


export const cleanupTempFile = async (filePath) => {
    try {
        await fs.unlink(filePath)
        logger.info(`Temp file deleted: ${filePath}`)
    } catch (error) {
        logger.error(`Error deleting temp file: ${filePath}`, error)
    }
}






