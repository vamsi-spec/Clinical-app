


import multer from 'multer'
import path from 'path'
import logger from '../utils/logger.js'
import { errorResponse } from '../utils/apiResponse.js'


const ALLOWED_AUDIO_FORMATS = [
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


//Storage - disk storage in temp folder
//files are upload to cloudinary immediatly
//after multer saves them then delete from disk

const storage = multer.diskStorage({
    destination: (_req,_file,cb) => {
        cb(null,'temp/')
    },
    filename: (_req,file,cb) => {
        const uniqueSuffix = `${Date.now()}-${Math.round(Math.random()*1e9)}`

        const ext = Path.extname(file.originalname).toLowerCase()
        cb(null,`audio-${uniqueSuffix}${ext}`)
    }
})


//File filter
const fileFilter = (_req,file,cb) => {
    const mimeAllowed = ALLOWED_AUDIO_FORMATS.includes(file.mimetype)
    const ext = path.extname(file.originalname).toLowerCase()
    const extAllowed = ALLOWED_EXTENSIONS.includes(ext)

    if(mimeAllowed || extAllowed){
        cb(null,true)

    }else{
     cb(
      new Error(
        `Invalid file type. Allowed formats: ${ALLOWED_EXTENSIONS.join(', ')}`
      ),
      false
    )
  }
}

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

export const uploadAudio = (req,res,next) => {
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
    const fs = require('fs').promises
    try {
        await fs.unlink(filePath)
        logger.info(`Temp file deleted: ${filePath}`)
    } catch (error) {
        logger.error(`Error deleting temp file: ${filePath}`, error)
    }
}


export const ensureTempDir = async () => {
  const fs = require('fs').promises
  try {
    await fs.mkdir('temp', { recursive: true })
    logger.info('✅ Temp directory ready')
  } catch (error) {
    logger.error('Failed to create temp directory:', error)
  }
}



