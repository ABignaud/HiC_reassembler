"""
Utilities to preprocess input data before feeding it to the various models.
cmdoret, 202102010
"""

import numpy as np
import pysam as ps
from typing import Tuple, Iterator

def get_matrix_regions(
    clr: cooler.Cooler,
    coords: "np.ndarray[int]",
    win_size: int,
) -> "np.ndarray[float]":
    """
    Samples evenly sized windows centered around input coordinates from
    a Hi-C matrix. 

    Parameters
    ----------
    clr :
        Cooler object containing Hi-C data.
    coords :
        Pairs of coordinates for which subsets should be generated. A window
        centered around each of these coordinates will be sampled. Dimensions
        are [N, 2].
    win_size :
        Size of windows to sample from the matrix.

    Returns
    -------
    win_stack :
        The 3D windows stack, with dimensions [N, win_size, win_size].
    """
    h, w = clr.shape
    i_w = int(h - win_size // 2)
    j_w = int(w - win_size // 2)

    # Only keep coords far enough from borders of the matrix
    valid_coords = np.where(
        (coords[:, 0] > int(win_size / 2))
        & (coords[:, 1] > int(win_size / 2))
        & (coords[:, 0] < i_w)
        & (coords[:, 1] < j_w)
    )[0]
    
    coords = coords[valid_coords, :]
    win_stack = np.zeros((coords.shape[0], win_size, win_size), dtype=np.float64)

    if win_size >= min(h, w):
        print("Window size must be smaller than the Hi-C matrix.")
    halfw = win_size // 2
    # Getting SV windows
    coords = coords.astype(int)
    for i in range(coords.shape[0]):
        c = coords[i, :]
        try:
            win = clr.matrix(sparse=False, balance=False)[
                (c[0] - halfw) : (c[0] + halfw),
                (c[1] - halfw) : (c[1] + halfw),
            ]
        except TypeError:
            breakpoint()
        win_stack[i, :, :] = win
    return win_stack


def chunk_matrix_diag(
    matrix: np.ndarray, size: int = 128, stride: int = 1
) -> Iterator[np.ndarray]:
    """
    Given an input matrix, yield a generator of chunks along the diagonal.
    Only compatible with symmetric matrices.

    Parameters
    ----------
    matrix : np.ndarray of floats
        Hi-C matrix to chunk.
    size :
        Size of the side of chunks.
    stride :
        Skip distance between chunks.

    Yields
    ------
    chunk : numpy.ndarray of floats
        Square tile on the diagonal.

    Examples
    --------
    >>> arr = np.array([[1, 0, 0], [0, 2, 0], [0, 0, 3]])
    >>> for i in matrix_diag_chunks(arr, size=2, stride=1): print(i)
    [[1 0]
     [0 2]]
    [[2 0]
     [0 3]]

    """
    m, n = matrix.shape
    # Sanity checks
    if m != n:
        raise ValueError("Input matrix must be square.")
    if (stride < 1) or not isinstance(stride, int):
        raise ValueError("Stride must be a strictly positive integer")
    if (size < 1) or not isinstance(size, int):
        raise ValueError("Size must be a strictly positive integer")
    # Iterate along diagonal and yield chunks
    for i in range(0, m - (size - 1), stride):
        start = i
        end = start + size
        chunk = matrix[start:end, start:end]
        yield chunk


def tile_matrix(
    matrix: np.ndarray, size: int = 128, stride: int = 1
) -> Iterator[Tuple[int, int, np.ndarray]]:
    """
    Chunk matrix into a grid of overlapping tiles and yield. Yield tiles and
    their coordinates. Works on asymmetric matrices.

    Parameters
    ----------
    matrix : numpy.ndarray of floats
        Hi-C matrix to tile.
    size : int
        Size of the side for the square tiles to generate.
    stride : int
        Skip distance between two tiles.

    Yields
    ------
    tuple of (int, int, numpy.ndarray of floats)
        The x, y coordinates of each tile and its content.

    Examples
    --------
    >>> arr = np.array([[1, 0, 0], [0, 2, 0], [0, 0, 3]])
    >>> for i in matrix_tiles(arr, size=2, stride=1):
    ...    print(i)
    (0, 0, array([[1, 0],
           [0, 2]]))
    (0, 1, array([[0, 0],
           [2, 0]]))
    (1, 0, array([[0, 2],
           [0, 0]]))
    (1, 1, array([[2, 0],
           [0, 3]]))
    """
    m, n = matrix.shape
    # Sanity checks
    if (stride < 1) or not isinstance(stride, int):
        raise ValueError("Stride must be a strictly positive integer")
    if (size < 1) or not isinstance(size, int):
        raise ValueError("Size must be a strictly positive integer")
    # Iterate along rows and then columns to yield chunks
    for i in range(0, m - (size - 1), stride):
        start_x, end_x = i, i + size
        for j in range(0, n - (size - 1), stride):
            start_y, end_y = j, j + size
            chunk = matrix[start_x:end_x, start_y:end_y]
            yield i, j, chunk


def get_bam_region_cov(file: str, region: str) -> np.ndarray:
    """Retrieves the basepair-level coverage track for a BAM region.

    Parameters
    ----------
    file : str
        path to the sorted, indexed BAM file.
    region : str
        UCSC-formatted region string (e.g. chr1:103-410)

    Returns
    -------
    numpy.ndarray of ints :
        number of reads overlapping each position in region.
    """

    bam = ps.AlignmentFile(file, "rb")
    chrom, start, end = parse_ucsc_region(region)

    cov_arr = np.zeros(end - start)
    for i, col in enumerate(bam.pileup(chrom, start, end, truncate=True)):
        cov_arr[i] = col.n

    return cov_arr


def get_bam_region_read_ends(file: str, region: str, side: str = "both") -> np.ndarray:
    """Retrieves the number of read ends at each position for a BAM region.

    Parameters
    ----------
    file : str
        path to the sorted, indexed BAM file.
    region : str
        UCSC-formatted region string (e.g. chr1:103-410)
    side : str
        What end of the reads to count: left, right or both.

    Returns
    -------
    numpy.ndarray of ints :
        counts of read extremities at each position in region.
    """

    bam = ps.AlignmentFile(file, "rb")
    chrom, start, end = parse_ucsc_region(region)

    start_arr = np.zeros(end - start)
    end_arr = np.zeros(end - start)
    for read in enumerate(bam.fetch(chrom, start, end)):
        start_arr[read.reference_start - start] += 1
        end_arr[read.reference_end - start] += 1

    if side == "left":
        return start_arr
    elif side == "right":
        return end_arr
    else:
        return start_arr + end_arr


def parse_ucsc_region(ucsc: str) -> Tuple[str, int, int]:
    """Parse a UCSC-formatted region string into a triplet (chrom, start, end).

    Parameters
    ----------
    ucsc : str
        String representing a genomic region in the format chromosome:start-end.

    Returns
    -------
    tuple of (str, int, int) :
        The individual values extracted from the UCSC string.

    Examples
    --------
    >>> parse_ucsc_region('chrX:10312-31231')
    ('chrX', 10312, 31231)
    """
    try:
        chrom, bp_range = ucsc.split(":")
        start, end = bp_range.split("-")
        start, end = int(start), int(end)
    except ValueError:
        raise ValueError("Invalid UCSC string.")
    return chrom, start, end


def pad_matrix(mat: np.ndarray, target_dim: int) -> np.ndarray:
    """
    Adds 0 padding on the right and bottom side of the input matrix to match
    target dimensions.

    Parameters
    ----------
    mat : numpy.ndarray of floats
        The input square matrix on which to add right and bottom zero padding.
    target_dim : int
        The size of the output (square) padded matrix.
    Returns
    -------
    mat : numpy.ndarray of floats
        The padded matrix of dimension target_dim x target_dim.

    Examples
    --------
    >>> arr = np.array([[1, 2], [3, 4]])
    >>> pad_matrix(arr, 3)
    array([[1., 2., 0.],
           [3., 4., 0.],
           [0., 0., 0.]])
    """

    padded = np.zeros((target_dim, target_dim), dtype=float)
    padded[: mat.shape[0], : mat.shape[1]] = mat

    return padded